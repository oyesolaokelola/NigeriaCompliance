# workflow/multimodal_parser.py
"""
Multimodal document parser for accurate layout preservation.

This module implements a document parser that uses vision LLMs to accurately extract
complex layouts from PDFs, including tables with merged cells, cross-page breaks,
and charts/graphs. Based on LlamaIndex's ParseBench prompts.

Key features:
- HTML tables with colspan/rowspan for merged cells
- Bounding box coordinates for layout preservation
- Category labels for layout elements
- Support for OpenAI, Anthropic, and Google models
"""

import base64
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


# Provider-specific prompts from LlamaIndex's ParseBench study
OPENAI_CLAUDE_SYSTEM_PROMPT = """You are a document parser. Your task is to convert document PDFs into clean, well-structured Markdown. Guidelines: 
- Preserve the document structure, including headings, paragraphs, lists, and tables. 
- Convert tables to HTML using `<table>`, `<tr>`, `<th>`, and `<td>`. 
- For existing tables in the document, use `colspan` and `rowspan` attributes to preserve merged cells and hierarchical headers. 
- For charts or graphs converted into tables, use flat combined column headers (for example, "Primary 2015" instead of separate header rows) so that each data cell's row contains all of its labels. 
- Describe images and figures briefly in square brackets, for example: `[Figure: description]`. 
- Preserve any code blocks with appropriate syntax highlighting. 
- Maintain reading order: left to right, top to bottom for Western documents. 
- Do not add commentary or explanations. Output only the parsed content. 
Additionally, wrap each layout element in a `<div>` tag with: 
- `data-bbox="[x1, y1, x2, y2]"` for the bounding box in normalized 0-1000 coordinates, where x is horizontal (left edge = 0, right edge = 1000) and y is vertical (top = 0, bottom = 1000). `x1, y1` is the top-left corner and `x2, y2` is the bottom-right corner. 
- `data-label="<category>"` where category is one of: `Caption`, `Footnote`, `Formula`, `List-item`, `Page-footer`, `Page-header`, `Picture`, `Section-header`, `Table`, `Text`, `Title`. 
Place elements in reading order. Every piece of content must be inside exactly one `<div>` wrapper."""

OPENAI_CLAUDE_USER_PROMPT = """The attached PDF is read from the input folder next to this script.
Parse the full document and output its content as clean markdown, with each layout element wrapped in a <div data-bbox="[x1,y1,x2,y2]" data-label="Category"> tag. Use HTML tables for any tabular data. For charts and graphs, use flat combined column headers. Output ONLY the parsed content with div wrappers and no explanations. """

GOOGLE_SYSTEM_PROMPT = """You are a document parser. Your task is to convert document PDFs into clean, well-structured Markdown. Guidelines: 
- Preserve the document structure, including headings, paragraphs, lists, and tables. 
- Convert tables to HTML using `<table>`, `<tr>`, `<th>`, and `<td>`. 
- For existing tables in the document, use `colspan` and `rowspan` attributes to preserve merged cells and hierarchical headers. 
- For charts or graphs converted into tables, use flat combined column headers (for example, "Primary 2015" instead of separate header rows) so that each data cell's row contains all of its labels. 
- Describe images and figures briefly in square brackets, for example: `[Figure: description]`. 
- Preserve any code blocks with appropriate syntax highlighting. 
- Maintain reading order: left to right, top to bottom for Western documents. 
- Do not add commentary or explanations. Output only the parsed content. 
Additionally, wrap each layout element in a `<div>` tag with: 
- `data-bbox="[y_min, x_min, y_max, x_max]"` for the bounding box in normalized 0-1000 coordinates where x is horizontal (left edge = 0, right edge = 1000) and y is vertical (top = 0, bottom = 1000). The order is `[y_min, x_min, y_max, x_max]`. 
- `data-label="<category>"` where category is one of: `Caption`, `Footnote`, `Formula`, `List-item`, `Page-footer`, `Page-header`, `Picture`, `Section-header`, `Table`, `Text`, `Title`. 
Place elements in reading order. Every piece of content must be inside exactly one `<div>` wrapper."""

GOOGLE_USER_PROMPT = """Parse this document page and output its content as clean markdown, with each layout element wrapped in a <div data-bbox="[y_min,x_min,y_max,x_max]" data-label="Category"> tag. Use HTML tables for any tabular data. For charts/graphs, use flat combined column headers. Output ONLY the parsed content with div wrappers, no explanations. """


@dataclass
class UsageRecord:
    """Record of token usage and cost for parsing operations"""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0


@dataclass
class ParseResult:
    """Result of document parsing"""
    raw_markdown: str
    clean_markdown: str
    html: Optional[str] = None
    usage: UsageRecord = None
    layout_elements: List[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.usage is None:
            self.usage = UsageRecord()
        if self.layout_elements is None:
            self.layout_elements = []


class MultimodalParser:
    """
    Multimodal document parser using vision LLMs for accurate layout extraction.
    
    Supports OpenAI, Anthropic, and Google model providers with configurable
    reasoning effort and table merging options.
    """
    
    def __init__(
        self,
        model_provider: str = "openai",
        model: str = "gpt-4o",
        reasoning_effort: str = "low",
        merge_table: bool = True,
        create_html: bool = True,
        additional_instructions: Optional[str] = None,
        api_key: Optional[str] = None
    ):
        """
        Initialize the multimodal parser.
        
        Args:
            model_provider: Provider to use ("openai", "anthropic", or "google")
            model: Model name (e.g., "gpt-4o", "claude-3-opus", "gemini-1.5-flash")
            reasoning_effort: Reasoning budget ("low", "medium", or "high")
            merge_table: Whether to merge tables split across pages
            create_html: Whether to generate HTML output
            additional_instructions: Domain-specific parsing instructions
            api_key: API key for the provider (if not in environment)
        """
        self.model_provider = model_provider.lower()
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.merge_table = merge_table
        self.create_html = create_html
        self.additional_instructions = additional_instructions or ""
        self.api_key = api_key
        
        # Validate provider
        if self.model_provider not in ["openai", "anthropic", "google"]:
            raise ValueError(f"Unsupported provider: {model_provider}")
        
        # Validate reasoning effort
        if self.reasoning_effort not in ["low", "medium", "high"]:
            raise ValueError(f"Invalid reasoning_effort: {reasoning_effort}")
    
    def parse(self, pdf_path: str) -> ParseResult:
        """
        Parse a PDF document using the configured vision LLM.
        
        Args:
            pdf_path: Path to the PDF file to parse
            
        Returns:
            ParseResult containing raw markdown, clean markdown, and optional HTML
        """
        pdf_file = Path(pdf_path)
        if not pdf_file.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        
        # Read PDF as bytes and encode as base64
        pdf_bytes = pdf_file.read_bytes()
        pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')
        
        # Build the prompt based on provider
        system_prompt, user_prompt = self._get_prompts()
        
        # Add additional instructions if provided
        if self.additional_instructions:
            user_prompt += f"\n\nAdditional instructions: {self.additional_instructions}"
        
        # Add table merging instruction if enabled
        if self.merge_table:
            user_prompt += "\n\nMerge tables that are split across pages into a single coherent table."
        
        # Call the appropriate provider API
        raw_response = self._call_llm_api(pdf_base64, system_prompt, user_prompt)
        
        # Clean up the response
        clean_markdown = self._clean_response(raw_response)
        
        # Extract layout elements
        layout_elements = self._extract_layout_elements(clean_markdown)
        
        # Generate HTML if requested
        html = None
        if self.create_html:
            html = self._markdown_to_html(clean_markdown)
        
        # Create usage record (placeholder - actual implementation would track tokens)
        usage = UsageRecord(
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            estimated_cost_usd=0.0
        )
        
        return ParseResult(
            raw_markdown=raw_response,
            clean_markdown=clean_markdown,
            html=html,
            usage=usage,
            layout_elements=layout_elements
        )
    
    def _get_prompts(self) -> tuple[str, str]:
        """Get the appropriate system and user prompts for the provider."""
        if self.model_provider in ["openai", "anthropic"]:
            return OPENAI_CLAUDE_SYSTEM_PROMPT, OPENAI_CLAUDE_USER_PROMPT
        elif self.model_provider == "google":
            return GOOGLE_SYSTEM_PROMPT, GOOGLE_USER_PROMPT
        else:
            raise ValueError(f"Unsupported provider: {self.model_provider}")
    
    def _call_llm_api(self, pdf_base64: str, system_prompt: str, user_prompt: str) -> str:
        """
        Call the LLM API with the PDF and prompts.
        
        Routes to the appropriate provider-specific implementation.
        """
        if self.model_provider == "openai":
            return self._call_openai_api(pdf_base64, system_prompt, user_prompt)
        elif self.model_provider == "anthropic":
            return self._call_anthropic_api(pdf_base64, system_prompt, user_prompt)
        elif self.model_provider == "google":
            return self._call_google_api(pdf_base64, system_prompt, user_prompt)
        else:
            raise ValueError(f"Unsupported provider: {self.model_provider}")
    
    def _call_openai_api(self, pdf_base64: str, system_prompt: str, user_prompt: str) -> str:
        """Call OpenAI's API for document parsing."""
        try:
            from openai import OpenAI
            
            # Get API key from parameter or environment
            api_key = self.api_key or os.environ.get("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OpenAI API key not found. Set OPENAI_API_KEY environment variable or pass api_key parameter.")
            
            client = OpenAI(api_key=api_key)
            
            # Prepare the message with the PDF as an image
            messages = [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:application/pdf;base64,{pdf_base64}"
                            }
                        },
                        {
                            "type": "text",
                            "text": user_prompt
                        }
                    ]
                }
            ]
            
            # Call the API
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=16384,
                temperature=0.1
            )
            
            return response.choices[0].message.content
            
        except ImportError:
            raise ImportError("OpenAI library not installed. Install with: pip install openai")
        except Exception as e:
            logger.error(f"Error calling OpenAI API: {e}")
            raise
    
    def _call_anthropic_api(self, pdf_base64: str, system_prompt: str, user_prompt: str) -> str:
        """Call Anthropic's Claude API for document parsing."""
        try:
            from anthropic import Anthropic
            
            # Get API key from parameter or environment
            api_key = self.api_key or os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError("Anthropic API key not found. Set ANTHROPIC_API_KEY environment variable or pass api_key parameter.")
            
            client = Anthropic(api_key=api_key)
            
            # Call the API
            message = client.messages.create(
                model=self.model,
                max_tokens=16384,
                system=system_prompt,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "application/pdf",
                                    "data": pdf_base64
                                }
                            },
                            {
                                "type": "text",
                                "text": user_prompt
                            }
                        ]
                    }
                ]
            )
            
            return message.content[0].text
            
        except ImportError:
            raise ImportError("Anthropic library not installed. Install with: pip install anthropic")
        except Exception as e:
            logger.error(f"Error calling Anthropic API: {e}")
            raise
    
    def _call_google_api(self, pdf_base64: str, system_prompt: str, user_prompt: str) -> str:
        """Call Google's Gemini API for document parsing."""
        try:
            import google.generativeai as genai
            
            # Get API key from parameter or environment
            api_key = self.api_key or os.environ.get("GOOGLE_API_KEY")
            if not api_key:
                raise ValueError("Google API key not found. Set GOOGLE_API_KEY environment variable or pass api_key parameter.")
            
            genai.configure(api_key=api_key)
            
            # Create the model
            model = genai.GenerativeModel(self.model)
            
            # Configure generation parameters
            generation_config = genai.types.GenerationConfig(
                temperature=0.1,
                max_output_tokens=16384,
            )
            
            # Handle reasoning effort for supported models
            if "thinking" in self.model.lower() or self.reasoning_effort != "low":
                # For models that support reasoning effort
                generation_config.thinking_budget = {
                    "low": 1000,
                    "medium": 5000,
                    "high": 10000
                }.get(self.reasoning_effort, 1000)
            
            # Prepare the content
            content = [
                system_prompt,
                {
                    "mime_type": "application/pdf",
                    "data": pdf_base64
                },
                user_prompt
            ]
            
            # Call the API
            response = model.generate_content(
                content,
                generation_config=generation_config
            )
            
            return response.text
            
        except ImportError:
            raise ImportError("Google Generative AI library not installed. Install with: pip install google-generativeai")
        except Exception as e:
            logger.error(f"Error calling Google API: {e}")
            raise
    
    def _clean_response(self, raw_response: str) -> str:
        """
        Clean the LLM response by removing code block fences and extra whitespace.
        """
        # Remove markdown code block fences if present
        cleaned = re.sub(r'^```markdown?\s*\n', '', raw_response, flags=re.MULTILINE)
        cleaned = re.sub(r'\n```\s*$', '', cleaned, flags=re.MULTILINE)
        
        # Remove extra whitespace
        cleaned = cleaned.strip()
        
        return cleaned
    
    def _extract_layout_elements(self, markdown: str) -> List[Dict[str, Any]]:
        """
        Extract layout elements from the parsed markdown with their bounding boxes.
        
        Returns a list of dictionaries containing:
        - content: The text content of the element
        - bbox: The bounding box coordinates
        - category: The element category (Text, Table, Title, etc.)
        """
        elements = []
        
        # Regex to match div tags with data-bbox and data-label
        div_pattern = r'<div\s+data-bbox="([^"]+)"\s+data-label="([^"]+)">\s*(.*?)\s*</div>'
        matches = re.findall(div_pattern, markdown, re.DOTALL)
        
        for bbox, category, content in matches:
            elements.append({
                "bbox": bbox,
                "category": category,
                "content": content.strip()
            })
        
        return elements
    
    def _markdown_to_html(self, markdown: str) -> str:
        """
        Convert the cleaned markdown to HTML.
        
        This is a placeholder. A full implementation would use a markdown
        library like markdown2 or mistune to properly convert markdown to HTML
        while preserving the HTML table structure.
        """
        # For now, return the markdown as-is since it already contains HTML tables
        # A proper implementation would wrap it in proper HTML structure
        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Parsed Document</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; }}
        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f2f2f2; }}
        .Title {{ font-size: 24px; font-weight: bold; text-align: center; margin: 20px 0; }}
        .Section-header {{ font-size: 18px; font-weight: bold; margin: 15px 0; }}
    </style>
</head>
<body>
{markdown}
</body>
</html>"""
