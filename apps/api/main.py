from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from apps.api.database import Database
from apps.api.repositories import Repository
from apps.api.services.config_loader import ConfigLoader
from apps.api.services.execution_service import ExecutionService
from apps.api.services.orchestration import OrchestrationService
from apps.api.services.planning import PlanningService
from apps.api.services.provider_resolution import ProviderResolutionService, registered_domain, safe_hostname
from apps.api.services.verification import VerificationService


ROOT_DIR = Path(__file__).resolve().parents[2]
STATIC_DIR = ROOT_DIR / "apps" / "api" / "static"
TEMPLATES_DIR = ROOT_DIR / "apps" / "api" / "templates"
STORAGE_DIR = ROOT_DIR / "storage"
EVIDENCE_DIR = STORAGE_DIR / "evidence"
RUNS_DIR = STORAGE_DIR / "runs"

database = Database(ROOT_DIR / "data" / "mvp.db")
repository = Repository(database)
config_loader = ConfigLoader(ROOT_DIR)
provider_resolution_service = ProviderResolutionService(config_loader)
planning_service = PlanningService(config_loader)
execution_service = ExecutionService(repository, RUNS_DIR)
verification_service = VerificationService()
orchestration_service = OrchestrationService(
    repository=repository,
    provider_resolution_service=provider_resolution_service,
    planning_service=planning_service,
    execution_service=execution_service,
    verification_service=verification_service,
    evidence_dir=EVIDENCE_DIR,
)

app = FastAPI(title="仿冒网站自动化处置台", version="0.2.0")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/storage", StaticFiles(directory=STORAGE_DIR), name="storage")


class BatchRunRequest(BaseModel):
    customer_id: str
    urls: list[str]
    notes: str = ""
    auto_execute: bool = True
    auto_verify: bool = True


class TemplateUpdateRequest(BaseModel):
    content: str


class NameSiloSettingsUpdateRequest(BaseModel):
    entry_url: str
    channel_id: str = "namesilo-phishing-report"
    template_key: str = "namesilo_phishing_report"
    default_reporter_email: str = ""
    notes: str = ""


class NameSiloCustomerConfigRequest(BaseModel):
    reporter_email: str = ""
    official_website: str = ""


def parse_bool(value: str | bool | None, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def ensure_case_exists(case_id: int) -> dict:
    try:
        return repository.get_case(case_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def ensure_batch_exists(batch_id: int) -> dict:
    try:
        return repository.get_batch(batch_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.on_event("startup")
def startup() -> None:
    database.init()
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/namesilo", response_class=HTMLResponse)
def namesilo_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/bootstrap")
def bootstrap() -> dict:
    payload = config_loader.bootstrap()
    payload["stats"] = repository.stats()
    payload["automation_guide"] = config_loader.automation_guide()
    return payload


@app.get("/api/cases")
def list_cases() -> list[dict]:
    return repository.list_cases()


@app.get("/api/cases/{case_id}")
def get_case(case_id: int) -> dict:
    ensure_case_exists(case_id)
    return repository.get_case_bundle(case_id)


@app.post("/api/cases")
async def create_case(
    customer_id: str = Form(...),
    target_url: str = Form(...),
    notes: str = Form(""),
    evidence_file: UploadFile | None = File(default=None),
    auto_execute: str = Form("false"),
    auto_verify: str = Form("false"),
) -> dict:
    try:
        hostname = safe_hostname(target_url)
        target_domain = registered_domain(hostname)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"URL 解析失败：{exc}") from exc

    if not target_domain:
        raise HTTPException(status_code=400, detail="无法识别有效域名")

    try:
        config_loader.get_customer(customer_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    placeholder_path = EVIDENCE_DIR / f"{target_domain.replace('.', '_')}-placeholder.txt"
    evidence_path = placeholder_path

    if evidence_file and evidence_file.filename:
        suffix = Path(evidence_file.filename).suffix or ".bin"
        evidence_path = EVIDENCE_DIR / f"{target_domain.replace('.', '_')}{suffix}"
        with evidence_path.open("wb") as output:
            shutil.copyfileobj(evidence_file.file, output)
    else:
        placeholder_path.write_text(
            f"案例截图占位文件\n目标 URL: {target_url}\n备注: {notes or '无'}\n",
            encoding="utf-8",
        )

    case_record = repository.create_case(
        customer_id=customer_id,
        target_url=target_url,
        target_domain=target_domain,
        evidence_path=str(evidence_path),
        notes=notes,
    )
    orchestration_service.process_case(
        case_record["id"],
        auto_execute=parse_bool(auto_execute),
        auto_verify=parse_bool(auto_verify),
    )
    return {"case": repository.get_case(case_record["id"])}


@app.post("/api/cases/{case_id}/resolve")
def resolve_case(case_id: int) -> dict:
    case_record = ensure_case_exists(case_id)
    resolution = provider_resolution_service.resolve(case_record["target_url"])
    providers = repository.replace_provider_resolutions(case_id, resolution["providers"])
    return {
        "case": repository.get_case(case_id),
        "providers": providers,
        "resolver_meta": {
            "dns_nameservers": resolution["dns_nameservers"],
            "resolved_ips": resolution["resolved_ips"],
        },
    }


@app.post("/api/cases/{case_id}/plan")
def plan_case(case_id: int) -> dict:
    case_record = ensure_case_exists(case_id)
    providers = repository.list_provider_resolutions(case_id)
    if not providers:
        raise HTTPException(status_code=400, detail="请先完成责任商识别")
    actions = planning_service.plan(case_record=case_record, providers=providers)
    return {
        "case": repository.get_case(case_id),
        "actions": repository.replace_actions(case_id, actions),
    }


@app.post("/api/cases/{case_id}/execute")
def execute_case(case_id: int) -> dict:
    ensure_case_exists(case_id)
    if not repository.list_actions(case_id):
        raise HTTPException(status_code=400, detail="请先生成处置计划")
    execution_service.execute_case(case_id)
    return repository.get_case_bundle(case_id)


@app.post("/api/cases/{case_id}/verify")
def verify_case(case_id: int) -> dict:
    ensure_case_exists(case_id)
    return orchestration_service.verify_case(case_id)


@app.get("/api/batches")
def list_batches() -> list[dict]:
    return repository.list_batches()


@app.get("/api/batches/{batch_id}")
def get_batch(batch_id: int) -> dict:
    ensure_batch_exists(batch_id)
    return repository.get_batch_bundle(batch_id)


@app.post("/api/batches")
def create_batch(
    customer_id: str = Form(...),
    urls_text: str = Form(...),
    notes: str = Form(""),
    auto_execute: str = Form("true"),
    auto_verify: str = Form("true"),
) -> dict:
    try:
        config_loader.get_customer(customer_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    urls = [line.strip() for line in urls_text.splitlines() if line.strip()]
    if not urls:
        raise HTTPException(status_code=400, detail="请至少输入一个 URL")

    return orchestration_service.create_batch_from_urls(
        customer_id=customer_id,
        urls=urls,
        notes=notes,
        auto_execute=parse_bool(auto_execute, True),
        auto_verify=parse_bool(auto_verify, True),
    )


@app.post("/api/batches/{batch_id}/verify")
def verify_batch(batch_id: int) -> dict:
    ensure_batch_exists(batch_id)
    for case_record in repository.cases_for_batch(batch_id):
        orchestration_service.verify_case(case_record["id"])
    return repository.get_batch_bundle(batch_id)


@app.get("/api/admin/customers")
def admin_list_customers() -> list[dict]:
    return config_loader.list_customers()


@app.post("/api/admin/customers")
async def admin_upsert_customer(
    customer_id: str = Form(...),
    brand_name_cn: str = Form(...),
    brand_name_en: str = Form(...),
    legal_entity_cn: str = Form(...),
    legal_entity_en: str = Form(...),
    contact_email: str = Form(...),
    reporter_email: str = Form(""),
    official_website: str = Form(""),
    signature_cn: str = Form(""),
    signature_en: str = Form(""),
    business_license: UploadFile | None = File(default=None),
    trademark_certificate: UploadFile | None = File(default=None),
) -> dict:
    customer = config_loader.upsert_customer(
        {
            "customer_id": customer_id,
            "brand_name_cn": brand_name_cn,
            "brand_name_en": brand_name_en,
            "legal_entity_cn": legal_entity_cn,
            "legal_entity_en": legal_entity_en,
            "contact_email": contact_email,
            "reporter_email": reporter_email,
            "official_website": official_website,
            "signature_cn": signature_cn,
            "signature_en": signature_en,
        }
    )

    if business_license and business_license.filename:
        content = await business_license.read()
        config_loader.save_customer_asset(customer["customer_id"], "business_license", business_license.filename, content)
    if trademark_certificate and trademark_certificate.filename:
        content = await trademark_certificate.read()
        config_loader.save_customer_asset(
            customer["customer_id"], "trademark_certificate", trademark_certificate.filename, content
        )

    return config_loader.get_customer(customer["customer_id"])


@app.get("/api/admin/templates")
def admin_list_templates() -> list[dict]:
    return config_loader.list_templates()


@app.get("/api/admin/templates/{locale}/{template_key}")
def admin_get_template(locale: str, template_key: str) -> dict:
    try:
        return config_loader.get_template(locale, template_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.put("/api/admin/templates/{locale}/{template_key}")
def admin_update_template(locale: str, template_key: str, payload: TemplateUpdateRequest) -> dict:
    return config_loader.save_template(locale, template_key, payload.content)


@app.get("/api/admin/channels")
def admin_list_channels() -> list[dict]:
    return config_loader.list_channels()


@app.get("/api/admin/namesilo-settings")
def admin_get_namesilo_settings() -> dict:
    return config_loader.get_namesilo_settings()


@app.put("/api/admin/namesilo-settings")
def admin_update_namesilo_settings(payload: NameSiloSettingsUpdateRequest) -> dict:
    data = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
    return config_loader.save_namesilo_settings(data)


@app.put("/api/admin/customers/{customer_id}/namesilo-config")
def admin_update_customer_namesilo_config(customer_id: str, payload: NameSiloCustomerConfigRequest) -> dict:
    try:
        current = config_loader.get_customer(customer_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return config_loader.upsert_customer(
        {
            "customer_id": current["customer_id"],
            "reporter_email": payload.reporter_email,
            "official_website": payload.official_website,
        }
    )


@app.get("/api/admin/automation-guide")
def admin_automation_guide() -> dict:
    return config_loader.automation_guide()


@app.post("/api/tools/create_case")
async def tool_create_case(
    customer_id: str = Form(...),
    target_url: str = Form(...),
    notes: str = Form(""),
) -> JSONResponse:
    payload = await create_case(
        customer_id=customer_id,
        target_url=target_url,
        notes=notes,
        evidence_file=None,
        auto_execute="false",
        auto_verify="false",
    )
    return JSONResponse(payload)


@app.post("/api/tools/run_batch")
def tool_run_batch(payload: BatchRunRequest) -> dict:
    try:
        config_loader.get_customer(payload.customer_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return orchestration_service.create_batch_from_urls(
        customer_id=payload.customer_id,
        urls=payload.urls,
        notes=payload.notes,
        auto_execute=payload.auto_execute,
        auto_verify=payload.auto_verify,
    )


@app.post("/api/tools/resolve_providers/{case_id}")
def tool_resolve_providers(case_id: int) -> dict:
    return resolve_case(case_id)


@app.post("/api/tools/plan_actions/{case_id}")
def tool_plan_actions(case_id: int) -> dict:
    return plan_case(case_id)


@app.post("/api/tools/run_case/{case_id}")
def tool_run_case(case_id: int) -> dict:
    return execute_case(case_id)
