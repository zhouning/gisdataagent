import os
import re
import json
from pypdf import PdfReader
import geopandas as gpd
from .gis_processors import _resolve_path, _generate_output_path

def extract_metrics_from_pdf(pdf_path: str) -> dict:
    """
    Extracts land use area metrics from a PDF report.
    Returns a dict like: {'耕地': 1234.5, '林地': 567.8}
    """
    try:
        reader = PdfReader(_resolve_path(pdf_path))
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
            
        # Regex patterns to find "Type: Area Unit"
        # Example: "耕地面积为 1500.5 平方米" or "林地: 300 亩"
        # We normalize everything to square meters if possible, or just return raw numbers
        
        metrics = {}
        
        # Pattern: (Category)(...)(Number)(Unit)
        # Simplified for demo: Look for "XX面积" followed by number
        # e.g., "耕地面积 123.45"
        
        categories = ['耕地', '林地', '园地', '草地', '建设用地', '水域']
        
        for cat in categories:
            # Regex to find: Category...Number
            # \s* allows spaces
            # [:=为]? allows separators like :, =, 为
            # (\d+(\.\d+)?) captures the number
            pattern = re.compile(f"{cat}(?:面积|总量)?\s*[:=为]?\s*(\d+(?:\.\d+)?)")
            matches = pattern.findall(text)
            if matches:
                # Take the last match as it's often the summary
                val = float(matches[-1]) 
                metrics[cat] = val
                
        return {"metrics": metrics, "raw_text_summary": text[:200] + "..."}
        
    except Exception as e:
        return {"error": str(e)}

def check_consistency(pdf_path: str, shp_path: str, area_field: str = 'Shape_Area', unit_conversion: float = 1.0) -> dict:
    """
    [Governance Tool] Cross-checks metrics in a PDF report against a Shapefile.
    
    Args:
        pdf_path: Path to the planning document.
        shp_path: Path to the vector data.
        area_field: Field in SHP to sum up (default: Shape_Area).
        unit_conversion: Multiplier to convert SHP area to PDF unit (e.g. m2 to mu = 0.0015).
                         Default 1.0 assumes PDF uses same unit as SHP (usually m2).
    """
    try:
        # 1. Extract targets from PDF
        pdf_data = extract_metrics_from_pdf(pdf_path)
        if "error" in pdf_data:
            return {"status": "error", "message": f"PDF Error: {pdf_data['error']}"}
        
        targets = pdf_data.get("metrics", {})
        if not targets:
            return {"status": "warning", "message": "No metrics found in PDF. Please ensure format is like '耕地面积: 100'."}

        # 2. Calculate actuals from SHP
        gdf = gpd.read_file(_resolve_path(shp_path))
        
        # Ensure we have a type field. Try 'DLMC', 'LandType', 'Type'
        type_col = next((c for c in ['DLMC', 'LandType', 'Type', 'LX'] if c in gdf.columns), None)
        
        actuals = {}
        if type_col:
            # Group by type and sum area
            # We filter gdf to only include types found in PDF targets to avoid noise
            # Or we map typical SHP values to PDF categories
            
            # Simple fuzzy matching for demo
            summary = gdf.groupby(type_col)[area_field].sum() * unit_conversion
            
            for cat, target_val in targets.items():
                # specific logic: if cat='耕地', sum all rows where type_col contains '耕' or '水田'/'旱地'
                mask = gdf[type_col].astype(str).str.contains(cat)
                
                # Handling standard specific sub-types
                if cat == '耕地':
                    mask = mask | gdf[type_col].isin(['水田', '旱地', '水浇地'])
                elif cat == '林地':
                    mask = mask | gdf[type_col].isin(['有林地', '灌木林地', '果园']) # Orchard often grouped with Forest in broad stats
                    
                actual_val = gdf[mask][area_field].sum() * unit_conversion
                actuals[cat] = actual_val
        else:
            # No type column, maybe just total area?
            actuals['Total'] = gdf[area_field].sum() * unit_conversion

        # 3. Compare
        comparison = []
        for cat, target in targets.items():
            actual = actuals.get(cat, 0.0)
            diff = actual - target
            ratio = (diff / target) if target != 0 else 0
            
            status = "MATCH"
            if abs(ratio) > 0.05: status = "MISMATCH (>5%)"
            if abs(ratio) > 0.10: status = "SERIOUS MISMATCH (>10%)"
            
            comparison.append({
                "category": cat,
                "doc_value": target,
                "data_value": round(actual, 2),
                "diff": round(diff, 2),
                "status": status
            })
            
        return {
            "status": "success",
            "report": comparison,
            "doc_source": pdf_path,
            "data_source": shp_path
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}
