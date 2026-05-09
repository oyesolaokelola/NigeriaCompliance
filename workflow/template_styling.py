# workflow/template_styling.py
"""
Template-based styling extraction and application.

This module handles:
1. Extracting styling information (fonts, colors, spacing, layouts) from template documents
2. Storing styling profiles for reuse
3. Applying extracted styles to generated output documents
4. Supporting multiple template formats (DOCX, PDF)
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, asdict
import re

from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import pdfplumber

logger = logging.getLogger(__name__)


@dataclass
class FontStyle:
    """Extracted font styling information"""
    name: str = "Calibri"
    size: int = 11
    bold: bool = False
    italic: bool = False
    color: str = "000000"  # RGB hex
    

@dataclass
class ParagraphStyle:
    """Extracted paragraph styling information"""
    alignment: str = "left"  # left, center, right, justify
    line_spacing: float = 1.0
    space_before: int = 0
    space_after: int = 0
    indent_left: int = 0
    indent_right: int = 0
    

@dataclass
class SectionStyle:
    """Extracted section styling information"""
    heading_level: int = 1
    title_font: FontStyle = None
    body_font: FontStyle = None
    heading_font: FontStyle = None
    paragraph_style: ParagraphStyle = None
    margin_top: int = 720  # In twips (1/20th of a point)
    margin_bottom: int = 720
    

@dataclass
class TemplateProfile:
    """Complete styling profile extracted from a template document"""
    template_name: str
    template_path: str
    page_width: float = 8.5
    page_height: float = 11.0
    margin_left: int = 720
    margin_right: int = 720
    margin_top: int = 720
    margin_bottom: int = 720
    title_font: FontStyle = None
    heading_font: FontStyle = None
    body_font: FontStyle = None
    paragraph_style: ParagraphStyle = None
    section_styles: Dict[str, SectionStyle] = None
    table_style: str = "Light Grid Accent 1"
    color_scheme: Dict[str, str] = None
    header_content: str = ""
    footer_content: str = ""
    has_page_numbers: bool = False
    orientation: str = "portrait"
    

    def __post_init__(self):
        if self.title_font is None:
            self.title_font = FontStyle()
        if self.heading_font is None:
            self.heading_font = FontStyle()
        if self.body_font is None:
            self.body_font = FontStyle()
        if self.paragraph_style is None:
            self.paragraph_style = ParagraphStyle()
        if self.section_styles is None:
            self.section_styles = {}
        if self.color_scheme is None:
            self.color_scheme = {}


class TemplateExtractor:
    """Extracts styling information from template documents"""
    
    def __init__(self):
        self.supported_formats = ['.docx', '.pdf']
    
    def extract_from_docx(self, template_path: Path) -> TemplateProfile:
        """Extract styling from a DOCX template"""
        try:
            doc = Document(template_path)
            profile = TemplateProfile(
                template_name=template_path.stem,
                template_path=str(template_path)
            )
            
            # Extract page layout
            section = doc.sections[0]
            profile.margin_left = section.left_margin.twips
            profile.margin_right = section.right_margin.twips
            profile.margin_top = section.top_margin.twips
            profile.margin_bottom = section.bottom_margin.twips
            
            # Extract fonts from paragraphs
            title_fonts = []
            heading_fonts = []
            body_fonts = []
            
            for para in doc.paragraphs[:20]:  # Sample first 20 paragraphs
                if not para.text.strip():
                    continue
                    
                for run in para.runs:
                    font = run.font
                    font_style = FontStyle(
                        name=font.name or "Calibri",
                        size=int(font.size.pt) if font.size else 11,
                        bold=font.bold or False,
                        italic=font.italic or False,
                        color=self._extract_font_color(font)
                    )
                    
                    # Classify font by size and usage
                    if font.size and font.size.pt >= 18:
                        title_fonts.append(font_style)
                    elif font.size and font.size.pt >= 14:
                        heading_fonts.append(font_style)
                    else:
                        body_fonts.append(font_style)
            
            # Set dominant styles
            profile.title_font = title_fonts[0] if title_fonts else FontStyle(size=28, bold=True)
            profile.heading_font = heading_fonts[0] if heading_fonts else FontStyle(size=14, bold=True)
            profile.body_font = body_fonts[0] if body_fonts else FontStyle(size=11)
            
            # Extract paragraph styles
            for para in doc.paragraphs:
                if para.text.strip():
                    pPr = para._element.pPr
                    if pPr is not None:
                        profile.paragraph_style = self._extract_paragraph_style(pPr)
                        break
            
            # Extract header/footer
            if doc.sections[0].header.paragraphs:
                header_text = " ".join([p.text for p in doc.sections[0].header.paragraphs])
                profile.header_content = header_text[:100]
            
            if doc.sections[0].footer.paragraphs:
                footer_text = " ".join([p.text for p in doc.sections[0].footer.paragraphs])
                profile.footer_content = footer_text[:100]
            
            # Check for page numbers in footer
            profile.has_page_numbers = "page" in profile.footer_content.lower()
            
            # Extract table style if tables exist
            if doc.tables:
                profile.table_style = "Light Grid Accent 1"  # Default Word style
            
            logger.info(f"Successfully extracted template profile from {template_path}")
            return profile
            
        except Exception as e:
            logger.error(f"Error extracting DOCX template: {e}")
            raise
    
    def extract_from_pdf(self, template_path: Path) -> TemplateProfile:
        """Extract styling information from a PDF template"""
        try:
            profile = TemplateProfile(
                template_name=template_path.stem,
                template_path=str(template_path)
            )
            
            with pdfplumber.open(template_path) as pdf:
                # Extract page info
                if pdf.pages:
                    page = pdf.pages[0]
                    # PDF measurements are in points
                    profile.page_width = page.width / 72  # Convert to inches
                    profile.page_height = page.height / 72
                    
                    # Extract text and fonts
                    for obj in page.chars[:50]:  # Sample first 50 chars
                        if obj.get('name'):
                            font_size = int(obj.get('size', 11))
                            if font_size >= 18:
                                profile.title_font = FontStyle(
                                    name=obj.get('name', 'Helvetica'),
                                    size=font_size
                                )
                            elif font_size >= 14:
                                profile.heading_font = FontStyle(
                                    name=obj.get('name', 'Helvetica'),
                                    size=font_size
                                )
                            else:
                                profile.body_font = FontStyle(
                                    name=obj.get('name', 'Helvetica'),
                                    size=font_size
                                )
            
            logger.info(f"Successfully extracted template profile from PDF {template_path}")
            return profile
            
        except Exception as e:
            logger.error(f"Error extracting PDF template: {e}")
            raise
    
    def extract(self, template_path: str) -> TemplateProfile:
        """Extract styling from any supported template format"""
        path = Path(template_path)
        
        if not path.exists():
            raise FileNotFoundError(f"Template file not found: {template_path}")
        
        if path.suffix.lower() == '.docx':
            return self.extract_from_docx(path)
        elif path.suffix.lower() == '.pdf':
            return self.extract_from_pdf(path)
        else:
            raise ValueError(f"Unsupported template format: {path.suffix}")
    
    @staticmethod
    def _extract_font_color(font) -> str:
        """Extract RGB color from font"""
        try:
            if font.color and font.color.rgb:
                return font.color.rgb.string.lstrip('#')
            return "000000"
        except:
            return "000000"
    
    @staticmethod
    def _extract_paragraph_style(pPr) -> ParagraphStyle:
        """Extract paragraph properties from OOXML element"""
        style = ParagraphStyle()
        
        # Alignment
        jc = pPr.find(qn('w:jc'))
        if jc is not None:
            align_map = {'left': 'left', 'center': 'center', 'right': 'right', 'both': 'justify'}
            style.alignment = align_map.get(jc.get(qn('w:val')), 'left')
        
        # Line spacing
        spacing = pPr.find(qn('w:spacing'))
        if spacing is not None:
            line = spacing.get(qn('w:line'))
            if line:
                style.line_spacing = int(line) / 240
        
        # Space before/after
        if spacing is not None:
            before = spacing.get(qn('w:before'))
            after = spacing.get(qn('w:after'))
            if before:
                style.space_before = int(before)
            if after:
                style.space_after = int(after)
        
        return style


class StyleApplier:
    """Applies extracted template styles to generated documents"""
    
    def __init__(self, template_profile: TemplateProfile):
        self.profile = template_profile
    
    def apply_to_docx(self, doc: Document) -> Document:
        """Apply template styling to a DOCX document"""
        try:
            # Apply margins
            for section in doc.sections:
                section.left_margin = self.profile.margin_left
                section.right_margin = self.profile.margin_right
                section.top_margin = self.profile.margin_top
                section.bottom_margin = self.profile.margin_bottom
                
                # Apply header/footer if template has them
                if self.profile.header_content:
                    header = section.header.paragraphs[0] if section.header.paragraphs else section.header.add_paragraph()
                    header.text = self.profile.header_content
                
                if self.profile.footer_content or self.profile.has_page_numbers:
                    footer = section.footer.paragraphs[0] if section.footer.paragraphs else section.footer.add_paragraph()
                    if self.profile.has_page_numbers:
                        footer.text = self.profile.footer_content or "Page "
            
            # Apply styles to paragraphs
            for i, para in enumerate(doc.paragraphs):
                if i == 0:  # Title
                    self._apply_font_style(para, self.profile.title_font)
                    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                elif i < 3:  # Headings
                    self._apply_font_style(para, self.profile.heading_font)
                else:  # Body
                    self._apply_font_style(para, self.profile.body_font)
                    self._apply_paragraph_style(para, self.profile.paragraph_style)
            
            # Apply styles to tables
            for table in doc.tables:
                self._apply_table_style(table)
            
            logger.info("Successfully applied template styles to document")
            return doc
            
        except Exception as e:
            logger.error(f"Error applying template styles: {e}")
            return doc
    
    @staticmethod
    def _apply_font_style(para, font_style: FontStyle):
        """Apply font styling to a paragraph"""
        for run in para.runs:
            run.font.name = font_style.name
            run.font.size = Pt(font_style.size)
            run.font.bold = font_style.bold
            run.font.italic = font_style.italic
            
            # Set color
            try:
                rgb = bytes.fromhex(font_style.color)
                run.font.color.rgb = RGBColor(*rgb)
            except:
                pass
    
    @staticmethod
    def _apply_paragraph_style(para, para_style: ParagraphStyle):
        """Apply paragraph styling"""
        pPr = para._element.get_or_add_pPr()
        
        # Set spacing
        spacing = OxmlElement('w:spacing')
        spacing.set(qn('w:line'), str(int(para_style.line_spacing * 240)))
        spacing.set(qn('w:before'), str(para_style.space_before))
        spacing.set(qn('w:after'), str(para_style.space_after))
        pPr.append(spacing)
        
        # Set indentation
        if para_style.indent_left > 0 or para_style.indent_right > 0:
            ind = OxmlElement('w:ind')
            ind.set(qn('w:left'), str(para_style.indent_left))
            ind.set(qn('w:right'), str(para_style.indent_right))
            pPr.append(ind)
    
    @staticmethod
    def _apply_table_style(table):
        """Apply table styling"""
        tbl = table._element
        tblPr = tbl.tblPr
        if tblPr is None:
            tblPr = OxmlElement('w:tblPr')
            tbl.insert(0, tblPr)
        
        # Set table style
        tblStyle = OxmlElement('w:tblStyle')
        tblStyle.set(qn('w:val'), 'LightGridAccent1')
        tblPr.append(tblStyle)


class TemplateManager:
    """Manages template storage and retrieval"""
    
    def __init__(self, template_dir: Path = None):
        if template_dir is None:
            template_dir = Path(__file__).resolve().parent.parent / "templates"
        self.template_dir = template_dir
        self.template_dir.mkdir(exist_ok=True, parents=True)
        self.profiles_cache_file = self.template_dir / "profiles.json"
    
    def register_template(self, template_path: str, profile_name: str = None) -> TemplateProfile:
        """Extract and register a template"""
        extractor = TemplateExtractor()
        profile = extractor.extract(template_path)
        
        if profile_name:
            profile.template_name = profile_name
        
        # Save profile to cache
        self._save_profile(profile)
        logger.info(f"Registered template: {profile.template_name}")
        return profile
    
    def get_template_profile(self, template_name: str) -> Optional[TemplateProfile]:
        """Retrieve a cached template profile"""
        profiles = self._load_profiles()
        for profile_dict in profiles.get("templates", []):
            if profile_dict.get("template_name") == template_name:
                return self._dict_to_profile(profile_dict)
        return None
    
    def list_templates(self) -> List[str]:
        """List all registered templates"""
        profiles = self._load_profiles()
        return [p.get("template_name") for p in profiles.get("templates", [])]
    
    def _save_profile(self, profile: TemplateProfile):
        """Save profile to cache file"""
        profiles = self._load_profiles()
        profile_dict = asdict(profile)
        
        # Convert nested dataclasses
        if profile.title_font:
            profile_dict['title_font'] = asdict(profile.title_font)
        if profile.heading_font:
            profile_dict['heading_font'] = asdict(profile.heading_font)
        if profile.body_font:
            profile_dict['body_font'] = asdict(profile.body_font)
        if profile.paragraph_style:
            profile_dict['paragraph_style'] = asdict(profile.paragraph_style)
        
        # Update or add
        existing = None
        for i, p in enumerate(profiles.get("templates", [])):
            if p.get("template_name") == profile.template_name:
                existing = i
                break
        
        if existing is not None:
            profiles["templates"][existing] = profile_dict
        else:
            profiles.setdefault("templates", []).append(profile_dict)
        
        with open(self.profiles_cache_file, 'w') as f:
            json.dump(profiles, f, indent=2)
    
    def _load_profiles(self) -> dict:
        """Load all cached profiles"""
        if self.profiles_cache_file.exists():
            try:
                with open(self.profiles_cache_file, 'r') as f:
                    return json.load(f)
            except:
                return {"templates": []}
        return {"templates": []}
    
    @staticmethod
    def _dict_to_profile(data: dict) -> TemplateProfile:
        """Convert dict to TemplateProfile"""
        # Handle nested dataclasses
        for key in ['title_font', 'heading_font', 'body_font', 'paragraph_style']:
            if key in data and isinstance(data[key], dict):
                if key == 'paragraph_style':
                    data[key] = ParagraphStyle(**data[key])
                else:
                    data[key] = FontStyle(**data[key])
        
        return TemplateProfile(**data)
