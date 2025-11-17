import os
import io
import uuid
from datetime import datetime
from typing import List, Optional, Dict

import requests
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from database import db, create_document, get_documents
from schemas import Project, ProcessURLRequest, RegenerateRequest, ExportQuery

# AI placeholders: we implement rule-based stub that can be upgraded to OpenAI later
# To keep the app functional without external keys, we won't call real OpenAI here.
# The extraction/generation functions are deterministic and fast.

app = FastAPI(title="Auto-Explainer for Developers API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SECTIONS = [
    "instagram_post",
    "facebook_post",
    "reels_script",
    "selling_points",
    "whatsapp_short",
    "qa",
    "sales_call_script",
]

LANGS = ["en", "pl"]

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


def simple_extract(text: str) -> dict:
    """Very simple heuristic extractor from raw text/images.
    In production, replace with GPT-vision or PDF parsers.
    """
    lower = text.lower()
    data = {
        "location": "",
        "prices": "",
        "sizes": "",
        "payment_plan": "",
        "amenities": [],
        "usp": [],
        "handover": "",
        "developer": "",
        "project": "",
    }

    # crude heuristics
    for key in ["location", "handover", "developer", "project"]:
        if key in lower:
            start = lower.find(key)
            snippet = text[start:start+160]
            data[key] = snippet.split("\n")[0]

    if "price" in lower or "from" in lower:
        data["prices"] = "From competitive entry pricing; exact figures detected when using AI mode."
    if "sqft" in lower or "sqm" in lower or "bed" in lower:
        data["sizes"] = "Studios to 4BR; sizes auto-detected in AI mode."
    if "payment" in lower or "installment" in lower:
        data["payment_plan"] = "Flexible installments available."
    if "amenit" in lower or "pool" in lower or "gym" in lower:
        data["amenities"] = ["Pool", "Gym", "Parking"]
    data["usp"] = ["Prime location", "Strong ROI potential"]

    return data


def generate_content(extracted: dict, tone: str, lang: str) -> dict:
    """Generate seven content formats in EN/PL with chosen tone.
    This is a lightweight template-based generator to keep app runnable.
    """
    name = extracted.get("project") or "New Development"
    location = extracted.get("location", "")
    prices = extracted.get("prices", "")
    sizes = extracted.get("sizes", "")
    payment = extracted.get("payment_plan", "")
    amenities = ", ".join(extracted.get("amenities", []))
    usp = ", ".join(extracted.get("usp", []))
    handover = extracted.get("handover", "")
    developer = extracted.get("developer", "")

    def t(en, pl):
        return pl if lang == "pl" else en

    def apply_tone(text):
        if tone == "aggressive":
            return t("ACT NOW: ", "DZIAŁAJ TERAZ: ") + text
        if tone == "simple":
            return t("Plain: ", "Prosto: ") + text
        if tone == "storytelling":
            return t("Imagine this: ", "Wyobraź sobie: ") + text
        return t("Premium: ", "Premium: ") + text

    instagram = apply_tone(
        t(
            f"{name} in {location}. {prices} {sizes} {payment} Amenities: {amenities}. Handover: {handover}. By {developer}.",
            f"{name} w {location}. {prices} {sizes} {payment} Udogodnienia: {amenities}. Handover: {handover}. Deweloper: {developer}.",
        )
    )

    facebook = apply_tone(
        t(
            f"Discover {name}. Key points: {usp}. Prices: {prices}. Sizes: {sizes}. Payment: {payment}. Location: {location}.",
            f"Poznaj {name}. Kluczowe atuty: {usp}. Ceny: {prices}. Metraże: {sizes}. Płatność: {payment}. Lokalizacja: {location}.",
        )
    )

    reels = apply_tone(
        t(
            f"Hook: Own {name} in {location}.\n- {usp}\n- {prices}\n- {sizes}\n- {payment}\nCTA: DM for details.",
            f"Hook: {name} w {location}.\n- {usp}\n- {prices}\n- {sizes}\n- {payment}\nCTA: Napisz po szczegóły.",
        )
    )

    selling_points = apply_tone(
        t(
            f"Top 10: {usp}, Amenities: {amenities}, Handover: {handover}, Developer: {developer}",
            f"Top 10: {usp}, Udogodnienia: {amenities}, Handover: {handover}, Deweloper: {developer}",
        )
    )

    whatsapp = apply_tone(
        t(
            f"Short: {name} in {location}. {prices} {payment}",
            f"Krótko: {name} w {location}. {prices} {payment}",
        )
    )

    qa_items = [
        t("What is the starting price?", "Jaka jest cena startowa?"),
        t("What sizes are available?", "Jakie metraże są dostępne?"),
        t("What is the payment plan?", "Jaki jest plan płatności?"),
        t("Where is it located?", "Gdzie znajduje się inwestycja?"),
        t("When is handover?", "Kiedy odbiory?"),
        t("Who is the developer?", "Kto jest deweloperem?"),
        t("What amenities are included?", "Jakie udogodnienia?"),
        t("Expected ROI?", "Oczekiwany zwrot?"),
        t("Is financing available?", "Czy dostępne jest finansowanie?"),
        t("How to reserve?", "Jak zarezerwować?"),
    ]
    qa = "\n".join([f"Q: {q}\nA: " for q in qa_items])

    call_script = apply_tone(
        t(
            f"Intro: calling about {name}. Confirm interest, share {prices} & {payment}, schedule viewing.",
            f"Intro: dzwonię w sprawie {name}. Potwierdź zainteresowanie, podaj {prices} i {payment}, umów prezentację.",
        )
    )

    return {
        "instagram_post": instagram,
        "facebook_post": facebook,
        "reels_script": reels,
        "selling_points": selling_points,
        "whatsapp_short": whatsapp,
        "qa": qa,
        "sales_call_script": call_script,
    }


def build_outputs(extracted: dict, tone: str, languages: List[str]):
    outputs = {}
    for lang in languages:
        outputs[lang] = generate_content(extracted, tone, lang)
    return outputs


@app.get("/")
def root():
    return {"message": "Auto-Explainer API running"}


@app.post("/api/process/url")
def process_url(payload: ProcessURLRequest):
    # Fetch text content from URL (basic). In production handle PDFs/HTML properly.
    try:
        r = requests.get(payload.url, timeout=10)
        content = r.text[:5000]
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch: {e}")

    extracted = simple_extract(content)
    outputs = build_outputs(extracted, payload.tone, payload.languages)

    project = Project(
        title=extracted.get("project") or payload.url,
        source_type="url",
        source_url=payload.url,
        tone=payload.tone,
        extracted=extracted,
        outputs=outputs,
    )
    project_id = create_document("project", project)
    return {"id": project_id, "project": project.model_dump()}


@app.post("/api/process/upload")
def process_upload(
    file: UploadFile = File(...),
    tone: str = Form("premium"),
):
    # Save file locally
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".pdf", ".png", ".jpg", ".jpeg"]:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    saved = os.path.join(UPLOAD_DIR, f"{uuid.uuid4().hex}{ext}")
    content = file.file.read()
    with open(saved, "wb") as f:
        f.write(content)

    # Stub: we can't OCR here; use filename as source for heuristics
    text_hint = file.filename
    extracted = simple_extract(text_hint)
    outputs = build_outputs(extracted, tone, LANGS)

    project = Project(
        title=extracted.get("project") or os.path.basename(file.filename),
        source_type="upload",
        file_path=saved,
        tone=tone,
        extracted=extracted,
        outputs=outputs,
    )
    project_id = create_document("project", project)
    return {"id": project_id, "project": project.model_dump()}


@app.get("/api/projects")
def list_projects(limit: int = 50):
    docs = get_documents("project", {}, limit)
    # convert ObjectId to string if present
    for d in docs:
        if "_id" in d:
            d["id"] = str(d.pop("_id"))
    return {"projects": docs}


@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    from bson import ObjectId
    doc = db["project"].find_one({"_id": ObjectId(project_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    doc["id"] = str(doc.pop("_id"))
    return {"project": doc}


class OutputsPayload(BaseModel):
    outputs: Dict[str, Dict[str, str]]


@app.post("/api/projects/{project_id}/update_outputs")
def update_outputs(project_id: str, payload: OutputsPayload):
    from bson import ObjectId
    result = db["project"].update_one({"_id": ObjectId(project_id)}, {"$set": {"outputs": payload.outputs, "updated_at": datetime.utcnow()}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"status": "ok"}


@app.post("/api/projects/{project_id}/regenerate")
def regenerate(project_id: str, payload: RegenerateRequest):
    from bson import ObjectId
    doc = db["project"].find_one({"_id": ObjectId(project_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")

    outputs = build_outputs(doc.get("extracted", {}), payload.tone, payload.languages)
    db["project"].update_one({"_id": ObjectId(project_id)}, {"$set": {"tone": payload.tone, "outputs": outputs, "updated_at": datetime.utcnow()}})

    return {"status": "ok"}


@app.post("/api/projects/{project_id}/export")
def export(project_id: str, query: ExportQuery):
    from bson import ObjectId
    doc = db["project"].find_one({"_id": ObjectId(project_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")

    fmt = query.format.lower()

    # Build a unified text for txt/pdf/docx; and JSON for json
    if fmt == "json":
        return JSONResponse(doc)

    def combined_text():
        lines = []
        lines.append(f"Title: {doc.get('title','')}")
        for lang, sections in (doc.get("outputs") or {}).items():
            lines.append(f"\n=== {lang.upper()} ===")
            for sec, val in sections.items():
                lines.append(f"\n## {sec}\n{val}")
        return "\n".join(lines)

    text_data = combined_text()

    if fmt == "txt":
        return StreamingResponse(io.BytesIO(text_data.encode("utf-8")), media_type="text/plain", headers={"Content-Disposition": "attachment; filename=export.txt"})

    if fmt == "pdf":
        # Minimal PDF using reportlab would require dependency; use txt fallback in a PDF MIME
        return StreamingResponse(io.BytesIO(text_data.encode("utf-8")), media_type="application/pdf", headers={"Content-Disposition": "attachment; filename=export.pdf"})

    if fmt == "docx":
        return StreamingResponse(io.BytesIO(text_data.encode("utf-8")), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": "attachment; filename=export.docx"})

    raise HTTPException(status_code=400, detail="Unsupported export format")


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set"
            response["database_name"] = db.name
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    import os as _os
    response["database_url"] = "✅ Set" if _os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if _os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
