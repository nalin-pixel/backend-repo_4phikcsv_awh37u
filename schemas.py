"""
Database Schemas for Auto-Explainer for Developers

Each Pydantic model maps to a MongoDB collection with the lowercase class name.
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class Project(BaseModel):
    """Represents one processed property development launch."""
    title: Optional[str] = Field(None, description="Detected project title/name")
    source_type: str = Field(..., description="'upload' or 'url'")
    source_url: Optional[str] = Field(None, description="If provided, the URL that was processed")
    file_path: Optional[str] = Field(None, description="Saved path to uploaded file if any")
    tone: str = Field("premium", description="premium | aggressive | simple | storytelling")

    # Extracted raw facts from materials
    extracted: Dict[str, Any] = Field(default_factory=dict, description="Structured details: prices, sizes, payment_plan, location, amenities, usp, handover, developer")

    # Generated outputs by language and section
    # outputs[lang][section] -> str
    outputs: Dict[str, Dict[str, str]] = Field(default_factory=dict)

class RegenerateRequest(BaseModel):
    tone: str = Field(..., description="premium | aggressive | simple | storytelling")
    languages: List[str] = Field(default_factory=lambda: ["en", "pl"])

class ProcessURLRequest(BaseModel):
    url: str
    tone: str = Field("premium")
    languages: List[str] = Field(default_factory=lambda: ["en", "pl"])

class ExportQuery(BaseModel):
    format: str = Field(..., description="txt | pdf | docx | json")
