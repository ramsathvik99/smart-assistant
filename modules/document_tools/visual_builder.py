"""
Visual Asset and Diagram Generator for Document Tools.
Generates publication-quality charts, architectural diagrams, flowcharts,
and neural network illustrations using matplotlib in headless mode (Agg).
Embeds seamlessly into Word (.docx), PDF (.pdf), and PowerPoint (.pptx).
"""

import os
import tempfile
import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("VisualBuilder")

# Configure matplotlib for headless execution
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np


def get_visual_cache_dir() -> str:
    """Returns directory for caching generated visual artifacts."""
    cache_dir = os.path.join(tempfile.gettempdir(), "smart_assistant_visuals")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def create_chart(
    chart_type: str,
    title: str,
    categories: List[str],
    series: Dict[str, List[float]],
    x_label: str = "",
    y_label: str = "",
    filename: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generate professional charts (bar, line, pie, grouped_bar).
    
    Args:
        chart_type: "bar", "horizontal_bar", "line", "pie", "grouped_bar"
        title: Chart title
        categories: Labels for x-axis or pie slices
        series: Dict of series_name -> values list (e.g. {"Accuracy": [85.2, 92.4, 96.1]})
        x_label: X-axis label
        y_label: Y-axis label
        filename: Optional output filename
    """
    try:
        fig, ax = plt.subplots(figsize=(8.5, 4.8), dpi=180)
        fig.patch.set_facecolor("#FFFFFF")
        ax.set_facecolor("#F8FAFC")

        palette = ["#1F497D", "#0EA5E9", "#10B981", "#F59E0B", "#8B5CF6", "#EF4444"]
        
        c_type = chart_type.lower()
        if c_type == "bar":
            series_name = list(series.keys())[0] if series else "Value"
            vals = list(series.values())[0] if series else [0] * len(categories)
            bars = ax.bar(categories, vals, color=palette[0], width=0.55, edgecolor="#0F172A", linewidth=0.8, zorder=3)
            # Add value labels
            for bar in bars:
                height = bar.get_height()
                ax.annotate(f"{height:g}",
                            xy=(bar.get_x() + bar.get_width() / 2, height),
                            xytext=(0, 3), textcoords="offset points",
                            ha='center', va='bottom', fontsize=9, fontweight='bold', color="#1E293B")
            ax.set_ylabel(y_label or series_name, fontsize=10, fontweight='bold', color="#1E293B")

        elif c_type == "horizontal_bar":
            series_name = list(series.keys())[0] if series else "Value"
            vals = list(series.values())[0] if series else [0] * len(categories)
            y_pos = np.arange(len(categories))
            bars = ax.barh(y_pos, vals, color=palette[1], height=0.55, edgecolor="#0369A1", linewidth=0.8, zorder=3)
            ax.set_yticks(y_pos)
            ax.set_yticklabels(categories, fontsize=9, color="#1E293B")
            for bar in bars:
                width = bar.get_width()
                ax.annotate(f"{width:g}",
                            xy=(width, bar.get_y() + bar.get_height() / 2),
                            xytext=(4, 0), textcoords="offset points",
                            ha='left', va='center', fontsize=9, fontweight='bold', color="#1E293B")
            ax.set_xlabel(x_label or series_name, fontsize=10, fontweight='bold', color="#1E293B")

        elif c_type == "grouped_bar":
            x = np.arange(len(categories))
            total_series = len(series)
            bar_width = 0.75 / max(total_series, 1)
            for idx, (s_name, s_vals) in enumerate(series.items()):
                offset = (idx - (total_series - 1) / 2) * bar_width
                color = palette[idx % len(palette)]
                ax.bar(x + offset, s_vals, bar_width, label=s_name, color=color, edgecolor="#334155", linewidth=0.6, zorder=3)
            ax.set_xticks(x)
            ax.set_xticklabels(categories, fontsize=9, color="#1E293B")
            ax.legend(frameon=True, facecolor="#FFFFFF", edgecolor="#CBD5E1")
            if y_label: ax.set_ylabel(y_label, fontsize=10, fontweight='bold', color="#1E293B")

        elif c_type == "line":
            for idx, (s_name, s_vals) in enumerate(series.items()):
                color = palette[idx % len(palette)]
                ax.plot(categories, s_vals, marker='o', linewidth=2.4, markersize=6, label=s_name, color=color, zorder=4)
                for i, v in enumerate(s_vals):
                    ax.annotate(f"{v:g}", (categories[i], v), textcoords="offset points", xytext=(0, 6),
                                ha='center', fontsize=8, fontweight='bold', color=color)
            ax.legend(frameon=True, facecolor="#FFFFFF", edgecolor="#CBD5E1")
            if y_label: ax.set_ylabel(y_label, fontsize=10, fontweight='bold', color="#1E293B")

        elif c_type == "pie":
            vals = list(series.values())[0] if series else [1] * len(categories)
            wedges, texts, autotexts = ax.pie(
                vals, labels=categories, autopct='%1.1f%%',
                colors=palette[:len(categories)],
                startangle=140,
                wedgeprops=dict(width=0.6, edgecolor='#FFFFFF', linewidth=1.5)
            )
            for t in texts: t.set_color("#1E293B"); t.set_fontsize(9)
            for at in autotexts: at.set_color("#FFFFFF"); at.set_fontweight('bold'); at.set_fontsize(8.5)

        if c_type != "pie":
            ax.grid(True, linestyle="--", alpha=0.5, color="#CBD5E1", zorder=0)
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.spines['left'].set_color("#94A3B8")
            ax.spines['bottom'].set_color("#94A3B8")
            if x_label: ax.set_xlabel(x_label, fontsize=10, fontweight='bold', color="#1E293B")

        ax.set_title(title, fontsize=13, fontweight='bold', pad=14, color="#0F172A")
        plt.tight_layout()

        if not filename:
            from core.semantic_file_naming import get_semantic_file_naming_service
            out_path, _ = get_semantic_file_naming_service().resolve_output_path(
                task_description=title,
                title=title,
                artifact_type="chart",
                extension=".png",
                output_dir=get_visual_cache_dir()
            )
        else:
            out_path = filename
        fig.savefig(out_path, dpi=180, bbox_inches='tight')
        plt.close(fig)

        return {"success": True, "filepath": out_path, "type": "chart", "title": title}
    except Exception as e:
        logger.error(f"[VisualBuilder] Chart creation failed: {e}")
        return {"success": False, "error": str(e)}


def create_process_flowchart(
    steps: List[Dict[str, str]],
    title: str = "Process Flow Diagram",
    filename: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generate an illustrative sequential process flowchart diagram.
    steps: [{"step": "1", "title": "Data Ingestion", "desc": "Batch & Stream"}]
    """
    try:
        n = len(steps)
        fig_width = max(8.5, n * 2.2)
        fig, ax = plt.subplots(figsize=(fig_width, 3.2), dpi=180)
        fig.patch.set_facecolor("#FFFFFF")
        ax.set_facecolor("#FFFFFF")
        ax.set_xlim(0, n * 2.5)
        ax.set_ylim(0, 3)
        ax.axis('off')

        ax.set_title(title, fontsize=13, fontweight='bold', pad=12, color="#0F172A")

        box_width = 1.9
        box_height = 1.4

        for i, s in enumerate(steps):
            x = 0.3 + i * 2.4
            y = 0.8
            # Box
            rect = patches.FancyBboxPatch(
                (x, y), box_width, box_height,
                boxstyle="round,pad=0.1,rounding_size=0.15",
                linewidth=1.2, edgecolor="#1F497D", facecolor="#F1F5F9"
            )
            ax.add_patch(rect)

            # Step Number Badge
            badge = patches.Circle((x + 0.3, y + box_height - 0.25), 0.18, facecolor="#1F497D", edgecolor="none")
            ax.add_patch(badge)
            ax.text(x + 0.3, y + box_height - 0.25, str(s.get("step", i + 1)),
                    ha='center', va='center', color="#FFFFFF", fontsize=8.5, fontweight='bold')

            # Title & Desc
            stitle = s.get("title", f"Step {i+1}")
            sdesc = s.get("desc", "")
            ax.text(x + 0.6, y + box_height - 0.25, stitle, ha='left', va='center',
                    fontsize=9.5, fontweight='bold', color="#0F172A")
            ax.text(x + 0.95, y + 0.45, sdesc, ha='center', va='center',
                    fontsize=8, color="#475569", wrap=True)

            # Arrow to next step
            if i < n - 1:
                arrow_start = x + box_width + 0.05
                arrow_end = arrow_start + 0.35
                ax.annotate(
                    "", xy=(arrow_end, y + box_height / 2), xytext=(arrow_start, y + box_height / 2),
                    arrowprops=dict(arrowstyle="->", color="#0EA5E9", lw=2.2, mutation_scale=15)
                )

        if not filename:
            from core.semantic_file_naming import get_semantic_file_naming_service
            out_path, _ = get_semantic_file_naming_service().resolve_output_path(
                task_description=title,
                title=title,
                artifact_type="flowchart",
                extension=".png",
                output_dir=get_visual_cache_dir()
            )
        else:
            out_path = filename
        fig.savefig(out_path, dpi=180, bbox_inches='tight')
        plt.close(fig)

        return {"success": True, "filepath": out_path, "type": "flowchart", "title": title}
    except Exception as e:
        logger.error(f"[VisualBuilder] Flowchart creation failed: {e}")
        return {"success": False, "error": str(e)}


def create_neural_network_diagram(
    layer_sizes: Optional[List[int]] = None,
    layer_names: Optional[List[str]] = None,
    title: str = "Artificial Neural Network Architecture",
    filename: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generate an authentic schematic diagram of an Artificial Neural Network.
    layer_sizes: e.g. [4, 6, 6, 3] (Input, Hidden 1, Hidden 2, Output)
    """
    try:
        if not layer_sizes:
            layer_sizes = [4, 6, 6, 2]
        if not layer_names:
            layer_names = ["Input Layer\n(x ∈ ℝ⁴)", "Hidden Layer 1\n(ReLU)", "Hidden Layer 2\n(ReLU)", "Output Layer\n(Softmax)"]

        fig, ax = plt.subplots(figsize=(9.0, 5.0), dpi=180)
        fig.patch.set_facecolor("#FFFFFF")
        ax.set_facecolor("#FFFFFF")
        ax.axis('off')

        num_layers = len(layer_sizes)
        max_nodes = max(layer_sizes)

        # Coordinate spaces
        x_spacing = 1.0 / (num_layers + 1)
        layer_colors = ["#0EA5E9", "#6366F1", "#8B5CF6", "#10B981"]

        # Store node positions
        node_coords = []

        for l_idx, count in enumerate(layer_sizes):
            x = (l_idx + 1) * x_spacing
            y_spacing = 0.8 / (count + 1)
            coords = []
            c = layer_colors[l_idx % len(layer_colors)]

            for n_idx in range(count):
                y = 0.9 - (n_idx + 1) * y_spacing
                coords.append((x, y))

            node_coords.append(coords)

        # Draw weight connections between adjacent layers
        for l_idx in range(num_layers - 1):
            curr_nodes = node_coords[l_idx]
            next_nodes = node_coords[l_idx + 1]
            for c_node in curr_nodes:
                for n_node in next_nodes:
                    ax.plot([c_node[0], n_node[0]], [c_node[1], n_node[1]],
                            color="#CBD5E1", alpha=0.45, linewidth=0.75, zorder=1)

        # Draw nodes and layer labels
        for l_idx, coords in enumerate(node_coords):
            c = layer_colors[l_idx % len(layer_colors)]
            for n_idx, (x, y) in enumerate(coords):
                circle = patches.Circle((x, y), 0.026, facecolor=c, edgecolor="#0F172A", linewidth=1.2, zorder=3)
                ax.add_patch(circle)

            # Layer name label at top
            label = layer_names[l_idx] if l_idx < len(layer_names) else f"Layer {l_idx+1}"
            ax.text(x, 0.96, label, ha='center', va='bottom', fontsize=8.5, fontweight='bold', color="#1E293B")

        # Mathematical notation annotations
        ax.text(0.5, 0.02, "Forward Propagation: z^[l] = W^[l]a^[l-1] + b^[l]  •  a^[l] = σ(z^[l])",
                ha='center', va='bottom', fontsize=9, fontstyle='italic', color="#475569")

        ax.set_title(title, fontsize=13, fontweight='bold', pad=18, color="#0F172A")
        plt.tight_layout()

        if not filename:
            from core.semantic_file_naming import get_semantic_file_naming_service
            out_path, _ = get_semantic_file_naming_service().resolve_output_path(
                task_description=title,
                title=title,
                artifact_type="diagram",
                extension=".png",
                output_dir=get_visual_cache_dir()
            )
        else:
            out_path = filename
        fig.savefig(out_path, dpi=180, bbox_inches='tight')
        plt.close(fig)

        return {"success": True, "filepath": out_path, "type": "ann_diagram", "title": title}
    except Exception as e:
        logger.error(f"[VisualBuilder] Neural net diagram failed: {e}")
        return {"success": False, "error": str(e)}


def create_architecture_diagram(
    tiers: List[Dict[str, Any]],
    title: str = "System Architecture Diagram",
    filename: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generate a clean multi-tier system architecture diagram.
    tiers: [
      {"name": "Client Layer", "components": ["Desktop UI", "CLI", "Web App"]},
      {"name": "Application & Orchestration", "components": ["Unified Router", "Goal Planner", "Document Engine"]},
      {"name": "Execution & Persistence", "components": ["File Builders", "Task Manager", "PostgreSQL"]}
    ]
    """
    try:
        num_tiers = len(tiers)
        fig, ax = plt.subplots(figsize=(9.2, 4.8), dpi=180)
        fig.patch.set_facecolor("#FFFFFF")
        ax.set_facecolor("#FFFFFF")
        ax.axis('off')
        ax.set_xlim(0, 10)
        ax.set_ylim(0, num_tiers * 2.2 + 0.5)

        ax.set_title(title, fontsize=13, fontweight='bold', pad=14, color="#0F172A")

        tier_colors = ["#E0F2FE", "#EDE9FE", "#ECFDF5", "#FEF3C7"]
        border_colors = ["#0284C7", "#7C3AED", "#059669", "#D97706"]

        for t_idx, tier in enumerate(reversed(tiers)):
            y = 0.4 + t_idx * 2.2
            t_name = tier.get("name", f"Tier {t_idx+1}")
            comps = tier.get("components", [])

            # Tier background container
            container = patches.FancyBboxPatch(
                (0.5, y), 9.0, 1.7,
                boxstyle="round,pad=0.1,rounding_size=0.15",
                linewidth=1.2, edgecolor=border_colors[t_idx % len(border_colors)],
                facecolor=tier_colors[t_idx % len(tier_colors)], alpha=0.65
            )
            ax.add_patch(container)

            # Tier Header
            ax.text(0.8, y + 1.45, t_name.upper(), fontsize=9, fontweight='bold',
                    color=border_colors[t_idx % len(border_colors)])

            # Component Boxes
            c_count = len(comps)
            if c_count > 0:
                comp_width = 8.0 / c_count - 0.25
                for c_idx, comp_name in enumerate(comps):
                    cx = 0.8 + c_idx * (comp_width + 0.25)
                    cy = y + 0.25
                    c_box = patches.FancyBboxPatch(
                        (cx, cy), comp_width, 0.95,
                        boxstyle="round,pad=0.08,rounding_size=0.1",
                        linewidth=1.0, edgecolor="#94A3B8", facecolor="#FFFFFF"
                    )
                    ax.add_patch(c_box)
                    ax.text(cx + comp_width / 2, cy + 0.48, comp_name,
                            ha='center', va='center', fontsize=8.5, fontweight='bold', color="#1E293B", wrap=True)

            # Connecting down-arrow to next tier below
            if t_idx > 0:
                ax.annotate("", xy=(5.0, y + 1.75), xytext=(5.0, y + 2.15),
                            arrowprops=dict(arrowstyle="->", color="#64748B", lw=1.6, mutation_scale=12))

        if not filename:
            from core.semantic_file_naming import get_semantic_file_naming_service
            out_path, _ = get_semantic_file_naming_service().resolve_output_path(
                task_description=title,
                title=title,
                artifact_type="diagram",
                extension=".png",
                output_dir=get_visual_cache_dir()
            )
        else:
            out_path = filename
        fig.savefig(out_path, dpi=180, bbox_inches='tight')
        plt.close(fig)

        return {"success": True, "filepath": out_path, "type": "arch_diagram", "title": title}
    except Exception as e:
        logger.error(f"[VisualBuilder] Architecture diagram failed: {e}")
        return {"success": False, "error": str(e)}


class VisualAssetBuilder:
    """Convenience facade for generating diagrams and charts."""

    @staticmethod
    def create_grouped_bar_chart(
        title: str,
        categories: List[str],
        series: Dict[str, List[float]],
        output_path: Optional[str] = None
    ) -> str:
        res = create_chart("grouped_bar", title, categories, series, filename=output_path)
        return res.get("filepath", "")

    @staticmethod
    def create_neural_network_diagram(
        title: str = "Artificial Neural Network Topology",
        layer_sizes: Optional[List[int]] = None,
        output_path: Optional[str] = None
    ) -> str:
        res = create_neural_network_diagram(layer_sizes=layer_sizes, title=title, filename=output_path)
        return res.get("filepath", "")

    @staticmethod
    def create_system_architecture_diagram(
        title: str = "System Architecture",
        tiers: Optional[List[Dict[str, Any]]] = None,
        output_path: Optional[str] = None
    ) -> str:
        if not tiers:
            tiers = [
                {"name": "Client Layer", "components": ["Desktop Assistant UI", "Visual Surface", "Voice Loop"]},
                {"name": "Orchestration Layer", "components": ["Unified Command Router", "Goal Planner", "Document Engine"]},
                {"name": "Execution & Storage", "components": ["Document Builders", "Conversion Registry", "PostgreSQL"]}
            ]
        res = create_architecture_diagram(tiers=tiers, title=title, filename=output_path)
        return res.get("filepath", "")

    @staticmethod
    def create_process_flowchart(
        title: str = "Process Flow",
        steps: Optional[List[Dict[str, str]]] = None,
        output_path: Optional[str] = None
    ) -> str:
        if not steps:
            steps = [
                {"step": "1", "title": "Analyze Request", "desc": "Extract scope & intent"},
                {"step": "2", "title": "LLM Synthesis", "desc": "Generate substantive content"},
                {"step": "3", "title": "Format Builder", "desc": "Render tables & visuals"},
                {"step": "4", "title": "Quality Validation", "desc": "Verify integrity & layout"}
            ]
        res = create_process_flowchart(steps=steps, title=title, filename=output_path)
        return res.get("filepath", "")

    @staticmethod
    def build_metric_chart(
        metrics: Dict[str, float],
        title: str = "Metric Performance Chart",
        output_path: Optional[str] = None
    ) -> str:
        categories = list(metrics.keys())
        series = {"Value": [float(v) for v in metrics.values()]}
        res = create_chart("bar", title, categories, series, filename=output_path)
        return res.get("filepath", "")


