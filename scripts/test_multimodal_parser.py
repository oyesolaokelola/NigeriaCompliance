#!/usr/bin/env python
"""
Test script for the multimodal document parser.

This script demonstrates how to use the multimodal parser to extract
content from PDF documents with accurate layout preservation.
"""

import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add the parent directory to the path to import workflow modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workflow.multimodal_parser import MultimodalParser
from workflow.config import Config


def test_multimodal_parser(pdf_path: str, provider: str = "openai", model: str = "gpt-4o"):
    """
    Test the multimodal parser with a PDF document.
    
    Args:
        pdf_path: Path to the PDF file to parse
        provider: Model provider (openai, anthropic, google)
        model: Model name to use
    """
    print(f"Testing multimodal parser with {provider}/{model}")
    print(f"PDF file: {pdf_path}")
    print("-" * 60)
    
    # Load configuration
    config = Config.load_multimodal_parser_config()
    config.update({
        "model_provider": provider,
        "model": model
    })
    
    # Validate configuration
    if not Config.validate_parser_config(config):
        print(f"Error: API key for {provider} not found in environment variables.")
        print(f"Please set {provider.upper()}_API_KEY environment variable.")
        return
    
    # Initialize parser
    parser = MultimodalParser(
        model_provider=config["model_provider"],
        model=config["model"],
        reasoning_effort=config["reasoning_effort"],
        merge_table=config["merge_table"],
        create_html=config["create_html"],
        additional_instructions=config.get("additional_instructions")
    )
    
    try:
        # Parse the PDF
        print("Parsing PDF...")
        result = parser.parse(pdf_path)
        
        print("\n✓ Parsing successful!")
        print(f"\nUsage statistics:")
        print(f"  Input tokens: {result.usage.input_tokens}")
        print(f"  Output tokens: {result.usage.output_tokens}")
        print(f"  Total tokens: {result.usage.total_tokens}")
        print(f"  Estimated cost: ${result.usage.estimated_cost_usd:.4f}")
        
        print(f"\nLayout elements found: {len(result.layout_elements)}")
        for element in result.layout_elements[:5]:  # Show first 5
            print(f"  - {element['category']}: {element['content'][:50]}...")
        
        # Save outputs
        output_dir = Path(__file__).parent.parent / "output"
        output_dir.mkdir(exist_ok=True)
        
        pdf_name = Path(pdf_path).stem
        
        # Save raw markdown
        raw_path = output_dir / f"{pdf_name}_raw.md"
        raw_path.write_text(result.raw_markdown, encoding='utf-8')
        print(f"\n✓ Saved raw markdown to: {raw_path}")
        
        # Save clean markdown
        clean_path = output_dir / f"{pdf_name}_clean.md"
        clean_path.write_text(result.clean_markdown, encoding='utf-8')
        print(f"✓ Saved clean markdown to: {clean_path}")
        
        # Save HTML if available
        if result.html:
            html_path = output_dir / f"{pdf_name}.html"
            html_path.write_text(result.html, encoding='utf-8')
            print(f"✓ Saved HTML to: {html_path}")
        
        print("\n" + "=" * 60)
        print("Test completed successfully!")
        
    except Exception as e:
        print(f"\n✗ Error during parsing: {e}")
        import traceback
        traceback.print_exc()


def test_extraction_integration(pdf_path: str):
    """
    Test the integration with the extraction module.
    
    Args:
        pdf_path: Path to the PDF file to parse
    """
    print("Testing extraction module integration")
    print(f"PDF file: {pdf_path}")
    print("-" * 60)
    
    from workflow.extraction import extract_pdf
    from workflow.config import Config
    
    # Load configuration
    config = Config.load_multimodal_parser_config()
    
    try:
        # Extract using multimodal parser
        result = extract_pdf(
            Path(pdf_path),
            use_multimodal_parser=True,
            parser_config=config
        )
        
        print("\n✓ Extraction successful!")
        print(f"File type: {result['file_type']}")
        print(f"Text length: {len(result['raw_text'])} characters")
        print(f"Tables found: {len(result['raw_tables'])}")
        
        if 'html_content' in result:
            print(f"HTML content available: Yes")
        
        if 'layout_elements' in result:
            print(f"Layout elements: {len(result['layout_elements'])}")
        
        if 'usage' in result:
            print(f"\nUsage statistics:")
            print(f"  Input tokens: {result['usage']['input_tokens']}")
            print(f"  Output tokens: {result['usage']['output_tokens']}")
            print(f"  Estimated cost: ${result['usage']['estimated_cost_usd']:.4f}")
        
    except Exception as e:
        print(f"\n✗ Error during extraction: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Test the multimodal document parser")
    parser.add_argument("pdf_path", help="Path to the PDF file to parse")
    parser.add_argument("--provider", default="openai", choices=["openai", "anthropic", "google"],
                       help="Model provider to use")
    parser.add_argument("--model", default="gpt-4o", help="Model name to use")
    parser.add_argument("--test-extraction", action="store_true",
                       help="Test extraction module integration instead of direct parser")
    
    args = parser.parse_args()
    
    if args.test_extraction:
        test_extraction_integration(args.pdf_path)
    else:
        test_multimodal_parser(args.pdf_path, args.provider, args.model)
