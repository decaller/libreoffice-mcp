import logging
import sys
import os
import contextlib

# Configure logging to stderr at the absolute top
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

# Silence noisy loggers
for name in ['ooodev', 'com.sun.star', 'mcp']:
    logging.getLogger(name).setLevel(logging.WARNING)

from typing import List, Dict
from ooodev.loader import Lo
from ooodev.loader.inst.options import Options
from ooodev.calc import CalcDoc
from ooodev.office.write import Write
from ooodev.write import WriteDoc
from ooodev.draw import DrawDoc
from ooodev.office.chart2 import Chart2
from ooodev.utils.kind.chart2_types import ChartTypes
from mcp.server.fastmcp import FastMCP, Context
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

class AppContext:
    def __init__(self):
        self.loader = None
        self.documents = {}
        self.next_id = 0
        self.output_dir = os.getenv("LIBREOFFICE_OUTPUT_DIR", "/home/open-webui/output")
        os.makedirs(self.output_dir, exist_ok=True)

    def start_office(self):
        if self.loader is None:
            try:
                # Redirect stdout to stderr during office loading to prevent any leakage
                with contextlib.redirect_stdout(sys.stderr):
                    self.loader = Lo.load_office(
                        connector=Lo.ConnectSocket(host="127.0.0.1", port=int(os.getenv("LIBREOFFICE_PORT", "2083"))),
                        opt=Options(log_level=30)
                    )
            except Exception as e:
                logger.error(f"Failed to connect to LibreOffice: {e}")
                raise
        return self.loader

    def get_document(self, doc_id: str):
        return self.documents.get(doc_id)

    def add_document(self, doc_id: str, doc):
        self.documents[doc_id] = doc

    def remove_document(self, doc_id: str):
        self.documents.pop(doc_id, None)

    def close_office(self):
        if self.loader is not None:
            with contextlib.redirect_stdout(sys.stderr):
                Lo.close_office()
            self.loader = None

@asynccontextmanager
async def app_lifespan(server: FastMCP):
    app_ctx = AppContext()
    try:
        app_ctx.start_office()
        yield app_ctx
    except Exception as e:
        logger.error(f"Error in LibreOffice lifespan: {e}")
        raise
    finally:
        for doc_id in list(app_ctx.documents.keys()):
            doc = app_ctx.get_document(doc_id)
            if doc:
                doc.close_doc()
            app_ctx.remove_document(doc_id)
        app_ctx.close_office()

mcp = FastMCP("LibreOffice OooDev MCP", lifespan=app_lifespan, host="0.0.0.0", port=8000)

# Core Document Management Tools
@mcp.tool()
def open_document(ctx: Context, url: str, doc_type: str) -> str:
    app_ctx = ctx.request_context.lifespan_context
    doc_types = {"writer": WriteDoc, "calc": CalcDoc, "draw": DrawDoc, "impress": DrawDoc, "base": None}
    if doc_type not in doc_types:
        raise RuntimeError(f"Invalid document type. Use: {', '.join(doc_types.keys())}")
    try:
        if doc_type == "base":
            doc = Lo.open_doc(fnm=url, loader=app_ctx.loader)
        else:
            doc_class = doc_types[doc_type]
            doc = doc_class.from_path(fnm=os.path.join(app_ctx.output_dir, url), lo_inst=app_ctx.loader)
        doc_id = f"doc_{app_ctx.next_id}"
        app_ctx.next_id += 1
        app_ctx.add_document(doc_id, doc)
        return doc_id
    except Exception as e:
        raise RuntimeError(f"Failed to open document: {str(e)}")

@mcp.tool()
def new_document(ctx: Context, doc_type: str) -> str:
    app_ctx = ctx.request_context.lifespan_context
    doc_types = {"writer": WriteDoc, "calc": CalcDoc, "draw": DrawDoc, "impress": DrawDoc, "base": None}
    if doc_type not in doc_types:
        raise RuntimeError(f"Invalid document type. Use: {', '.join(doc_types.keys())}")
    try:
        if doc_type == "base":
            doc = Lo.create_doc(doc_type="sbase", loader=app_ctx.loader)
        else:
            doc_class = doc_types[doc_type]
            doc = doc_class.create_doc(lo_inst=app_ctx.loader)
        doc_id = f"doc_{app_ctx.next_id}"
        app_ctx.next_id += 1
        app_ctx.add_document(doc_id, doc)
        return doc_id
    except Exception as e:
        raise RuntimeError(f"Failed to create new document: {str(e)}")
    
@mcp.tool()
def save_document(ctx: Context, doc_id: str, url: str) -> str:
    app_ctx = ctx.request_context.lifespan_context
    doc = app_ctx.get_document(doc_id)
    if not doc: raise RuntimeError("Document not found")
    try:
        doc.save_doc(fnm=os.path.join(app_ctx.output_dir, url))
        return f"Document saved to {url}"
    except Exception as e:
        raise RuntimeError(f"Failed to save document: {str(e)}")

@mcp.tool()
def close_document(ctx: Context, doc_id: str) -> str:
    app_ctx = ctx.request_context.lifespan_context
    doc = app_ctx.get_document(doc_id)
    if not doc: raise RuntimeError("Document not found")
    try:
        doc.close_doc()
        app_ctx.remove_document(doc_id)
        return f"Document {doc_id} closed"
    except Exception as e:
        raise RuntimeError(f"Failed to close document: {str(e)}")

@mcp.tool()
def get_sheet_names(ctx: Context, doc_id: str) -> List[str]:
    app_ctx = ctx.request_context.lifespan_context
    doc = app_ctx.get_document(doc_id)
    if not doc or not isinstance(doc, CalcDoc): raise RuntimeError("Document is not a spreadsheet")
    return doc.get_sheet_names()

@mcp.tool()
def get_cell_value(ctx: Context, doc_id: str, sheet_name: str, cell_address: str) -> str:
    app_ctx = ctx.request_context.lifespan_context
    doc = app_ctx.get_document(doc_id)
    if not doc or not isinstance(doc, CalcDoc): raise RuntimeError("Document is not a spreadsheet")
    sheet = doc.sheets.get_by_name(sheet_name)
    cell = sheet[cell_address]
    return "" if cell.is_empty() else str(cell.value)

@mcp.tool()
def set_cell_value(ctx: Context, doc_id: str, sheet_name: str, cell_address: str, value: str) -> str:
    app_ctx = ctx.request_context.lifespan_context
    doc = app_ctx.get_document(doc_id)
    if not doc or not isinstance(doc, CalcDoc): raise RuntimeError("Document is not a spreadsheet")
    sheet = doc.sheets.get_by_name(sheet_name)
    try:
        cell = sheet[cell_address]
        cell.value = float(value)
    except ValueError:
        cell.value = value
    return f"Set {cell_address} to {value}"

@mcp.tool()
def format_cell_range(ctx: Context, doc_id: str, sheet_name: str, range_address: str, font_name: str = "Arial", font_size: int = 12, bold: bool = False, italic: bool = False, alignment: str = "center") -> str:
    app_ctx = ctx.request_context.lifespan_context
    doc = app_ctx.get_document(doc_id)
    if not doc or not isinstance(doc, CalcDoc): raise RuntimeError("Document is not a spreadsheet")
    sheet = doc.sheets.get_by_name(sheet_name)
    rng = sheet.rng(range_address)
    rng.set_font_name(font_name)
    rng.set_font_size(font_size)
    if bold: rng.set_font_weight(150.0)
    if italic: rng.set_font_slant(1)
    alignment_map = {"left": "LEFT", "center": "CENTER", "right": "RIGHT"}
    if alignment.lower() not in alignment_map: raise RuntimeError("Invalid alignment")
    rng.set_hori_justification(alignment_map[alignment.lower()])
    return f"Formatted range {range_address}"

@mcp.tool()
def create_chart(ctx: Context, doc_id: str, sheet_name: str, range_address: str, target_cell: str, chart_type: str, title: str = "") -> str:
    app_ctx = ctx.request_context.lifespan_context
    doc = app_ctx.get_document(doc_id)
    if not doc or not isinstance(doc, CalcDoc): raise RuntimeError("Document is not a spreadsheet")
    sheet = doc.sheets.get_by_name(sheet_name)
    chart_types = {"column": ChartTypes.Column.TEMPLATE_STACKED.COLUMN, "bar": ChartTypes.Bar.TEMPLATE_STACKED.BAR, "line": ChartTypes.Line.TEMPLATE_LINE.LINE, "pie": ChartTypes.Pie.TEMPLATE_DONUT.PIE}
    if chart_type not in chart_types: raise RuntimeError("Invalid chart type")
    chart = sheet.charts.insert_chart(rng_obj=sheet.rng(range_address), cell_name=target_cell, width=15, height=11, diagram_name=chart_types[chart_type])
    if title: chart.set_title(title)
    return f"Created {chart_type} chart at {target_cell}"

if __name__ == "__main__":
    mcp.run(transport="sse")
