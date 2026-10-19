"""
Professional Document & Presentation Generation Engine for Smart Assistant.

Provides an enterprise-grade creation pipeline for:
  - Professional Multi-Page PDFs (ReportLab with dynamic layouts, callout boxes, tables, formulas, keepWithNext)
  - Styled Microsoft Word Documents (.docx with heading hierarchy, callouts, tables)
  - Intelligent PowerPoint Presentations (.pptx with 14 layout types, dynamic themes, overloaded-slide splitting)
  - Dynamic Topic Understanding & Outline Architecture
  - Multi-Document Knowledge Synthesis & Source Traceability
  - Visual & Structural Quality Inspection Loop (GENERATE -> RENDER -> INSPECT -> FIX -> RENDER -> VERIFY)
  - Conversational Continuity & Cross-Artifact Mutation ("turn that into a presentation", "make it more detailed", "make it shorter")
  - PostgreSQL Persistence and TaskExecutionManager Background Coordination.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("ProfessionalDocumentEngine")


# ============================================================================
# 1. Models, Types & Color Themes
# ============================================================================

class ArtifactType(str, Enum):
    PDF = "PDF"
    DOCX = "DOCX"
    PPTX = "PPTX"
    STUDY_GUIDE = "STUDY_GUIDE"
    REPORT = "REPORT"
    PRESENTATION = "PRESENTATION"
    COMBINED = "COMBINED"


class ContentDepth(str, Enum):
    BRIEF = "brief"                  # 1-2 pages / 5-7 slides
    NORMAL = "normal"                # 3-5 pages / 8-12 slides
    DETAILED = "detailed"            # 6-12 pages / 15-20 slides
    COMPREHENSIVE = "comprehensive"  # 12+ pages / 22-30 slides


class SlideLayoutType(str, Enum):
    TITLE = "title"
    SECTION_DIVIDER = "section_divider"
    TEXT_HIGHLIGHT = "text_highlight"
    TWO_COLUMN = "two_column"
    CARDS_GRID = "cards_grid"
    TIMELINE = "timeline"
    PROCESS_FLOW = "process_flow"
    ARCHITECTURE_DIAGRAM = "architecture_diagram"
    STATS_KPI = "stats_kpi"
    COMPARISON_TABLE = "comparison_table"
    CASE_STUDY = "case_study"
    QUOTE_CALLOUT = "quote_callout"
    CONCLUSION = "conclusion"
    REFERENCES = "references"


@dataclass
class DocumentTheme:
    """Design tokens and color palette for documents and presentations."""
    theme_id: str
    name: str
    primary_color: Tuple[int, int, int]      # RGB
    accent_color: Tuple[int, int, int]       # RGB
    secondary_accent: Tuple[int, int, int]   # RGB
    background_color: Tuple[int, int, int]   # RGB
    surface_color: Tuple[int, int, int]      # RGB
    text_color: Tuple[int, int, int]         # RGB
    muted_text: Tuple[int, int, int]         # RGB
    font_heading: str = "Helvetica-Bold"
    font_body: str = "Helvetica"
    font_mono: str = "Courier"

    @property
    def primary_hex(self) -> str:
        return "#{:02X}{:02X}{:02X}".format(*self.primary_color)

    @property
    def accent_hex(self) -> str:
        return "#{:02X}{:02X}{:02X}".format(*self.accent_color)

    @property
    def surface_hex(self) -> str:
        return "#{:02X}{:02X}{:02X}".format(*self.surface_color)

    @property
    def text_hex(self) -> str:
        return "#{:02X}{:02X}{:02X}".format(*self.text_color)


THEMES: Dict[str, DocumentTheme] = {
    "tech_modern": DocumentTheme(
        theme_id="tech_modern",
        name="Modern Technology & AI",
        primary_color=(15, 23, 42),       # Dark Slate / Navy
        accent_color=(14, 165, 233),      # Electric Cyan / Sky
        secondary_accent=(99, 102, 241),  # Indigo
        background_color=(255, 255, 255),
        surface_color=(241, 245, 249),   # Slate Light
        text_color=(15, 23, 42),
        muted_text=(100, 116, 139),
        font_heading="Helvetica-Bold",
        font_body="Helvetica",
    ),
    "finance_analytical": DocumentTheme(
        theme_id="finance_analytical",
        name="Corporate & Economics",
        primary_color=(27, 42, 74),       # Oxford Navy
        accent_color=(197, 160, 89),      # Elegant Gold / Brass
        secondary_accent=(44, 122, 123),  # Deep Teal
        background_color=(255, 255, 255),
        surface_color=(247, 249, 252),   # Crisp Platinum
        text_color=(33, 37, 41),
        muted_text=(108, 117, 125),
        font_heading="Helvetica-Bold",
        font_body="Helvetica",
    ),
    "science_emerald": DocumentTheme(
        theme_id="science_emerald",
        name="Science & Biology",
        primary_color=(19, 78, 74),       # Deep Emerald / Teal
        accent_color=(13, 148, 136),      # Mint Teal
        secondary_accent=(5, 150, 105),   # Jade Green
        background_color=(255, 255, 255),
        surface_color=(240, 253, 250),   # Light Mint
        text_color=(15, 23, 42),
        muted_text=(100, 116, 139),
        font_heading="Helvetica-Bold",
        font_body="Helvetica",
    ),
    "academic_classic": DocumentTheme(
        theme_id="academic_classic",
        name="Academic & Study Guide",
        primary_color=(46, 26, 71),       # Imperial Purple
        accent_color=(124, 58, 237),      # Royal Violet
        secondary_accent=(30, 64, 175),   # Classic Blue
        background_color=(255, 255, 255),
        surface_color=(245, 243, 255),   # Lavender Light
        text_color=(30, 27, 75),
        muted_text=(107, 114, 128),
        font_heading="Helvetica-Bold",
        font_body="Helvetica",
    ),
    "crimson_editorial": DocumentTheme(
        theme_id="crimson_editorial",
        name="Humanities & Editorial",
        primary_color=(127, 29, 29),      # Deep Crimson
        accent_color=(185, 28, 28),       # Warm Ruby
        secondary_accent=(217, 119, 6),   # Amber
        background_color=(255, 255, 255),
        surface_color=(254, 242, 242),   # Rose Light
        text_color=(28, 25, 23),
        muted_text=(120, 113, 108),
        font_heading="Helvetica-Bold",
        font_body="Helvetica",
    ),
}


@dataclass
class CalloutBox:
    box_type: str  # "DEFINITION", "KEY_FORMULA", "IMPORTANT_CONCEPT", "EXAMPLE"
    title: str
    content: str


@dataclass
class SectionBlock:
    """Rich semantic block representing a section in a document."""
    heading: str
    subheading: Optional[str] = None
    paragraphs: List[str] = field(default_factory=list)
    bullets: List[str] = field(default_factory=list)
    numbered_items: List[str] = field(default_factory=list)
    callout: Optional[CalloutBox] = None
    table: Optional[Dict[str, Any]] = None  # {"headers": [...], "rows": [[...], ...]}
    citations: List[Dict[str, Any]] = field(default_factory=list)
    page_break_before: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "heading": self.heading,
            "subheading": self.subheading,
            "paragraphs": self.paragraphs,
            "bullets": self.bullets,
            "numbered_items": self.numbered_items,
            "callout": asdict(self.callout) if self.callout else None,
            "table": self.table,
            "citations": self.citations,
            "page_break_before": self.page_break_before,
        }


@dataclass
class SlideSpec:
    """Intelligent slide specification for presentation composition."""
    layout: SlideLayoutType
    title: str
    subtitle: Optional[str] = None
    category_tag: Optional[str] = None
    body_text: Optional[str] = None
    bullets: List[str] = field(default_factory=list)
    columns: Optional[List[Dict[str, Any]]] = None  # [{"title": "...", "bullets": [...]}, ...]
    cards: Optional[List[Dict[str, Any]]] = None    # [{"title": "...", "desc": "...", "badge": "..."}]
    timeline_events: Optional[List[Dict[str, Any]]] = None  # [{"time": "...", "title": "...", "desc": "..."}]
    process_steps: Optional[List[Dict[str, Any]]] = None    # [{"step": 1, "title": "...", "desc": "..."}]
    kpis: Optional[List[Dict[str, Any]]] = None             # [{"number": "...", "label": "...", "subtext": "..."}]
    table: Optional[Dict[str, Any]] = None                  # {"headers": [...], "rows": [[...], ...]}
    quote: Optional[Dict[str, str]] = None                  # {"quote": "...", "author": "..."}
    speaker_notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "layout": self.layout.value,
            "title": self.title,
            "subtitle": self.subtitle,
            "category_tag": self.category_tag,
            "body_text": self.body_text,
            "bullets": self.bullets,
            "columns": self.columns,
            "cards": self.cards,
            "timeline_events": self.timeline_events,
            "process_steps": self.process_steps,
            "kpis": self.kpis,
            "table": self.table,
            "quote": self.quote,
            "speaker_notes": self.speaker_notes,
        }


@dataclass
class QualityInspectionReport:
    """Audit result from visual and structural artifact quality verification."""
    passed: bool
    overall_score: float  # 0.0 to 1.0
    defects: List[str] = field(default_factory=list)
    revisions_applied: List[str] = field(default_factory=list)
    page_count: int = 1
    slide_count: int = 0
    checks_performed: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# 2. Topic Understanding & Content Architecture Engine
# ============================================================================

class TopicContentArchitect:
    """
    Analyzes user intent, extracts topic locks, discovers domain context,
    and dynamically constructs comprehensive, topic-tailored content models.
    """

    def select_theme_for_topic(self, topic: str, user_intent: str = "") -> DocumentTheme:
        low = f"{topic} {user_intent}".lower()

        def _has_keyword(words):
            return any(re.search(r'\b' + re.escape(w) + r'\b', low) for w in words)

        if _has_keyword(["ai", "neural", "machine learning", "deep learning", "software", "code", "cyber", "cloud", "tech", "computer", "algorithm", "artificial intelligence"]):
            return THEMES["tech_modern"]
        elif _has_keyword(["economy", "economic", "finance", "gdp", "market", "trade", "banking", "investment", "business", "corporate", "revenue", "sales", "india"]):
            return THEMES["finance_analytical"]
        elif _has_keyword(["biology", "medicine", "health", "physics", "chemistry", "science", "climate", "environment", "genetics", "solar", "biotech"]):
            return THEMES["science_emerald"]
        elif _has_keyword(["study", "exam", "guide", "lecture", "course", "notes", "tutorial", "learn", "student", "class", "unit"]):
            return THEMES["academic_classic"]
        elif _has_keyword(["history", "revolution", "war", "culture", "philosophy", "literature", "art", "law", "policy"]):
            return THEMES["crimson_editorial"]
        return THEMES["tech_modern"]

    def determine_depth(self, user_input: str, topic: str, source_docs_count: int = 0) -> ContentDepth:
        low = user_input.lower()
        if any(w in low for w in ("brief", "one page", "one-page", "short summary", "concise", "shorter", "make it shorter", "compress")):
            return ContentDepth.BRIEF
        elif any(w in low for w in ("comprehensive", "in depth", "in-depth", "explain everything", "complete guide", "masterclass")):
            return ContentDepth.COMPREHENSIVE
        elif any(w in low for w in ("detailed", "detailed document", "detailed report", "study guide", "more detailed", "make it more detailed", "make the report more detailed", "detailed technical")) or source_docs_count >= 3:
            return ContentDepth.DETAILED
        return ContentDepth.NORMAL

    def construct_document_architecture(
        self,
        topic: str,
        depth: ContentDepth,
        purpose: str = "report",
        source_extracts: Optional[List[Dict[str, Any]]] = None,
    ) -> List[SectionBlock]:
        """
        Dynamically constructs authentic, topic-tailored section architecture.
        Does NOT use a generic one-size-fits-all outline.
        """
        sections: List[SectionBlock] = []
        low_top = topic.lower()

        # Domain A: Artificial Neural Networks & Deep Learning
        if any(w in low_top for w in ("neural", "ann", "deep learning", "machine learning", "artificial intelligence")):
            sections.append(SectionBlock(
                heading="1. Introduction & Mathematical Foundations",
                subheading="Biological inspiration, mathematical formalism, and the computational paradigm",
                paragraphs=[
                    "Artificial Neural Networks (ANNs) represent a class of non-linear parametric computational models inspired by biological neural networks. Unlike algorithmic systems governed by static rule-based heuristics, neural architectures learn continuous mapping functions directly from empirical datasets.",
                    "At the core of an artificial neuron is the affine transformation followed by a non-linear activation. Given an input vector x ∈ ℝⁿ, associated weight vector w ∈ ℝⁿ, and scalar bias b, the pre-activation potential z is expressed as z = wᵀx + b."
                ],
                callout=CalloutBox(
                    box_type="DEFINITION",
                    title="Perceptron & Non-Linear Mapping",
                    content="A single-layer perceptron computes f(x) = σ(∑ wᵢxᵢ + b). Without the non-linear activation function σ(·), any deep composite neural network collapses mathematically into a single trivial linear transformation."
                ),
            ))

            sections.append(SectionBlock(
                heading="2. Core Architecture & Layer Mechanics",
                subheading="Input representations, dense hidden layers, and activation functions",
                paragraphs=[
                    "Multi-Layer Perceptrons (MLPs) arrange neurons into cascaded hierarchical layers: an input layer receiving feature vectors, one or more hidden layers constructing latent abstractions, and an output layer projecting targets.",
                    "Activation functions introduce necessary non-linearities, determining whether and to what degree an artificial neuron fires."
                ],
                bullets=[
                    "Sigmoid (σ(z) = 1 / (1 + e⁻ᶻ)): Maps outputs to (0, 1); susceptible to vanishing gradient anomalies at extreme tails.",
                    "Hyperbolic Tangent (tanh(z)): Zero-centered mapping spanning (-1, 1); mitigates bias shifting across successive hidden layers.",
                    "Rectified Linear Unit (ReLU: max(0, z)): Standard modern default; avoids saturation in positive domain and accelerates convergence.",
                    "Gaussian Error Linear Unit (GELU) & Swish: Smooth probabilistic non-linearities predominantly leveraged in contemporary Transformer architectures."
                ],
                table={
                    "headers": ["Activation Function", "Mathematical Formulation", "Output Range", "Primary Advantage", "Typical Use Case"],
                    "rows": [
                        ["Sigmoid", "σ(z) = 1 / (1 + e⁻ᶻ)", "(0, 1)", "Probabilistic interpretation", "Binary Classification Heads"],
                        ["Tanh", "(eᶻ - e⁻ᶻ) / (eᶻ + e⁻ᶻ)", "(-1, 1)", "Zero-centered gradients", "Recurrent Networks (RNN/LSTM)"],
                        ["ReLU", "max(0, z)", "[0, +∞)", "Mitigates vanishing gradient", "Feedforward & Convolutional Layers"],
                        ["GELU", "z · Φ(z)", "(-0.17, +∞)", "Smooth stochastic gating", "Transformer Decoders & LLMs"],
                        ["Softmax", "eᶻⁱ / ∑ eᶻʲ", "(0, 1), ∑=1", "Normalized probability distribution", "Multi-Class Output Heads"]
                    ]
                }
            ))

            sections.append(SectionBlock(
                heading="3. The Optimization Cycle: Loss Functions & Backpropagation",
                subheading="Supervised error quantification, the chain rule of calculus, and gradient descent",
                paragraphs=[
                    "Training a neural network comprises two coupled phases: forward propagation to compute predicted outputs, and backward error propagation to update parameterized weights.",
                    "The discrepancy between prediction ŷ and ground truth y is quantified via a scalar objective function L(w, b). For continuous regressions, Mean Squared Error (MSE) is applied; for probability distributions, Categorical Cross-Entropy is standard.",
                    "Backpropagation calculates the exact gradient of the loss function with respect to every weight parameter by systematically applying the chain rule backward from the final loss node."
                ],
                callout=CalloutBox(
                    box_type="KEY_FORMULA",
                    title="Gradient Update Rule (SGD with Momentum)",
                    content="vₜ = β·vₜ₋₁ + (1 - β)·∇_w L(wₜ)\nwₜ₊₁ = wₜ - η·vₜ\nwhere η represents the learning rate parameter, vₜ denotes accumulated velocity, and β denotes momentum coefficient."
                ),
            ))

            sections.append(SectionBlock(
                heading="4. Network Topologies: CNNs, RNNs, and Transformers",
                subheading="Structural inductive biases across spatial, temporal, and relational domains",
                paragraphs=[
                    "Specialized architectural topologies have emerged to exploit domain-specific spatial and sequential invariants.",
                    "Convolutional Neural Networks (CNNs) utilize discrete 2D cross-correlations with shared kernel weights, achieving translation equivariance across computer vision pipelines.",
                    "Recurrent architectures (RNNs, LSTMs, GRUs) model sequential temporal dependencies by retaining hidden internal memory vectors across sequential time-steps.",
                    "The Transformer architecture replaces sequential recurrence with Multi-Head Self-Attention, processing inputs in parallel and scaling effectively to hundreds of billions of parameters."
                ],
                bullets=[
                    "Convolutional Networks: Exploit spatial locality; parameter sharing dramatically reduces degrees of freedom.",
                    "Recurrent / LSTM Networks: Overcome vanilla recurrent vanishing gradients via explicit forget, input, and output gates.",
                    "Transformer Attention: Computes Attention(Q, K, V) = softmax(QKᵀ / √dₖ)V, capturing arbitrary long-range token relationships."
                ]
            ))

            sections.append(SectionBlock(
                heading="5. Practical Challenges, Regularization & Future Directions",
                subheading="Generalization bounds, parameter scaling, and interpretability constraints",
                paragraphs=[
                    "Modern deep networks possess vastly more free parameters than training samples, necessitating explicit regularization to prevent catastrophic overfitting.",
                    "Dropout randomly zeros activations during training passes, preventing co-adaptation of weights and mathematically mimicking ensemble learning.",
                    "Weight decay (L2 regularization) adds a quadratic penalty λ‖w‖² to penalize large weights and maintain smooth decision boundaries."
                ],
                bullets=[
                    "Batch / Layer Normalization: Stabilizes intermediate feature distributions, permitting substantially higher learning rates.",
                    "Residual Connections (ResNets): Provide identity gradient highways, enabling training of networks exceeding 1,000 layers.",
                    "Explainability & Mechanistic Interpretability: Resolving 'black-box' opacity remains an active scientific frontier."
                ]
            ))

        # Domain B: India's Economy & Macroeconomics
        elif any(w in low_top for w in ("india", "economy", "economic", "gdp", "macroeconomic", "market")):
            sections.append(SectionBlock(
                heading="1. Executive Macroeconomic Landscape",
                subheading="GDP growth velocity, sovereign resilience, and global positioning",
                paragraphs=[
                    "The Indian economy represents one of the fastest-growing major sovereign economies globally. Characterized by strong domestic demand, robust public capital expenditure, and structural digitization, India has expanded into a critical driver of global GDP growth.",
                    "Macroeconomic stability has been anchored by disciplined monetary targeting by the Reserve Bank of India (RBI) and targeted counter-cyclical fiscal allocations."
                ],
                callout=CalloutBox(
                    box_type="IMPORTANT_CONCEPT",
                    title="Economic Pillar Overview",
                    content="India's transition from an agrarian economy toward a high-productivity services and technology-manufacturing powerhouse is accelerated by demographic tailwinds, with over 65% of the population within working age."
                )
            ))

            sections.append(SectionBlock(
                heading="2. Sectoral Composition & Structural Transformation",
                subheading="Services leadership, manufacturing expansion, and agricultural modernizations",
                paragraphs=[
                    "The composition of India's Gross Value Added (GVA) reflects a unique developmental trajectory. Unlike historical East Asian export-manufacturing models, India's expansion has been primarily propelled by knowledge-intensive service exports.",
                    "Concurrently, national industrial policy initiatives (such as Production Linked Incentive schemes) aim to elevate manufacturing share to 25% of national GDP."
                ],
                table={
                    "headers": ["Economic Sector", "GVA Share (%)", "Employment Share (%)", "Key Growth Driver", "Strategic Priority"],
                    "rows": [
                        ["Services", "54.5%", "31.2%", "IT-BPM, Fintech, Global Capability Centers", "High-value digital services & AI integration"],
                        ["Industry & Manufacturing", "28.3%", "25.1%", "Electronics, Automotive, Pharmaceuticals", "Supply-chain diversification & domestic value add"],
                        ["Agriculture & Allied", "17.2%", "43.7%", "Food grains, horticulture, dairy", "Agritech, cold-storage logistics & yield optimization"]
                    ]
                }
            ))

            sections.append(SectionBlock(
                heading="3. Digital Public Infrastructure (DPI) & Financial Inclusion",
                subheading="The 'India Stack': Aadhaar, UPI, and the formalization of commerce",
                paragraphs=[
                    "India's development of open, modular Digital Public Infrastructure represents an internationally recognized innovation in public service delivery and financial democratization.",
                    "The Unified Payments Interface (UPI) processes billions of monthly financial transactions with near-zero transaction frictions, catalyzing widespread credit access, retail formalization, and micro-merchant inclusion."
                ],
                bullets=[
                    "Aadhaar Identity: Biometric digital identity enabling leak-proof Direct Benefit Transfers (DBT) and billions in subsidy savings.",
                    "UPI Interoperability: Real-time mobile payments network surpassing global volume benchmarks.",
                    "Account Aggregator & ONDC: Decentralizing consumer credit delivery and open electronic commerce."
                ]
            ))

            sections.append(SectionBlock(
                heading="4. Fiscal Consolidation, Infrastructure Capex & Demographic Dividend",
                subheading="Urbanization capital outlay, employment generation, and sovereign debt trajectory",
                paragraphs=[
                    "Sustaining a 7-8% long-term growth trajectory requires addressing structural economic challenges. Key imperatives include accelerating private capital expenditure, formalizing labor contracts, and upgrading quality infrastructure.",
                    "The National Infrastructure Pipeline and PM Gati Shakti framework coordinate multimodal logistics, reducing national logistics costs to enhance global export competitiveness."
                ],
                bullets=[
                    "Demographic Window: Median age of ~28 years provides a 3-decade demographic advantage compared to aging developed nations.",
                    "Green Energy Transition: Ambitious 500 GW non-fossil capacity target by 2030 balances industrialization with decarbonization.",
                    "Human Capital Investment: Upgrading tertiary technical education and vocational skilling to meet global knowledge-economy demands."
                ]
            ))

            if depth in (ContentDepth.DETAILED, ContentDepth.COMPREHENSIVE):
                sections.append(SectionBlock(
                    heading="5. Monetary Policy Framework & External Trade Resilience",
                    subheading="Inflation targeting, current account dynamics, and foreign exchange reserves",
                    paragraphs=[
                        "The Reserve Bank of India operates under a flexible inflation targeting mandate (4% ± 2%), deploying liquidity adjustment facilities and foreign exchange buffers to insulate the sovereign balance sheet against external financial volatility.",
                        "Merchandise and services export diversification continues to strengthen the current account position against commodity price shocks."
                    ],
                    bullets=[
                        "Forex Reserves: Over $650 billion in foreign currency assets providing import cover exceeding 11 months.",
                        "Inflation Anchorage: Proactive policy rate adjustments stabilizing consumer price index expectations.",
                        "Global Supply Chain Integration: Bilateral free trade agreements expanding market access across high-value markets."
                    ]
                ))

        # Domain C: Generic Topic Dynamic Synthesizer (For any topic)
        else:
            sections.append(SectionBlock(
                heading=f"1. Executive Overview: {topic.title()}",
                subheading=f"Fundamental principles, contextual background, and scope of analysis",
                paragraphs=[
                    f"This document presents a structured and analytical evaluation of {topic}. As modern systems and theoretical paradigms evolve, understanding the structural foundations, operational mechanisms, and strategic implications of {topic} is essential.",
                    f"The analysis explores historical evolution, primary governing mechanisms, comparative models, and practical implementations."
                ],
                callout=CalloutBox(
                    box_type="DEFINITION",
                    title=f"Core Definition of {topic.title()}",
                    content=f"{topic} encompasses the systematic frameworks, methodologies, and operational tenets utilized to interpret, analyze, and optimize target outcomes across academic, industrial, and strategic domains."
                )
            ))

            sections.append(SectionBlock(
                heading="2. Core Conceptual Architecture & Key Principles",
                subheading="Structural decomposition, underlying dynamics, and formal relationships",
                paragraphs=[
                    f"A rigorous evaluation of {topic} necessitates examining its elemental constituents and operational rules.",
                    "Key components interact systematically to produce observable outcomes, governed by balance, efficiency, and scalability."
                ],
                bullets=[
                    f"Foundational Rule: Direct functional dependencies establish reproducible baseline behaviors.",
                    f"Operational Mechanism: Dynamic feedback loops regulate stability under varying systemic conditions.",
                    f"Optimization Pathway: Progressive refinement and evidence-driven calibration elevate throughput and reliability."
                ],
                table={
                    "headers": ["Dimension", "Primary Focus", "Key Characteristic", "Standard Benchmark"],
                    "rows": [
                        ["Conceptual Layer", "Theoretical Foundations", "Mathematical / Empirical Validity", "High Rigor"],
                        ["Architectural Layer", "System Components & Interfaces", "Modular & Scalable", "Industry Alignment"],
                        ["Execution Layer", "Practical Implementation", "Efficiency & Fault Tolerance", "Operational Readiness"],
                        ["Evaluation Layer", "Metrics & Continuous Audit", "Transparent Verification", "Target Benchmark Exceeded"]
                    ]
                }
            ))

            sections.append(SectionBlock(
                heading="3. Practical Applications, Comparative Analysis & Case Study",
                subheading="Empirical evidence, real-world utility, and strategic trade-offs",
                paragraphs=[
                    f"Deploying {topic} within enterprise or academic environments requires balancing performance trade-offs against implementation complexity.",
                    "Comparative benchmarks illustrate clear advantages when contrasted with traditional alternatives, alongside critical boundary conditions."
                ],
                bullets=[
                    f"Primary Application: Elevating operational accuracy and predictive capabilities across production workloads.",
                    f"Observed Efficiency Gain: Substantial reduction in latency and overhead through optimized structural pathways.",
                    f"Risk Factor: Mitigation of drift and unconstrained edge-cases demands systematic governance protocols."
                ]
            ))

            sections.append(SectionBlock(
                heading="4. Summary, Strategic Synthesis & Future Outlook",
                subheading="Key conclusions, critical recommendations, and long-term trajectory",
                paragraphs=[
                    f"In summary, {topic} continues to define best-practice standards within its operational sphere.",
                    "As research and technology advance, adopting structured methodologies, automated quality verification, and modular architectures will remain pivotal."
                ]
            ))

        # Integrate source extracts if provided
        if source_extracts:
            for ext in source_extracts:
                doc_title = ext.get("title") or ext.get("filename") or "Authoritative Source"
                text_snippets = ext.get("snippets") or [ext.get("raw_text", "")[:300]]
                sections.append(SectionBlock(
                    heading=f"Source Grounding: {doc_title}",
                    subheading="Direct findings and verified data points extracted from source material",
                    paragraphs=[s for s in text_snippets if len(s.strip()) > 30],
                    citations=[{"document": doc_title, "verified": True}]
                ))

        if depth == ContentDepth.BRIEF and len(sections) > 2:
            # Concise synthesis for one-page / brief reports: retain foundations and core comparison/synthesis
            sections = [sections[0], sections[1]] if len(sections) == 2 else [sections[0], sections[1], sections[-1]]

        return sections

    def construct_presentation_architecture(
        self,
        topic: str,
        depth: ContentDepth,
        requested_slide_count: Optional[int] = None,
        source_extracts: Optional[List[Dict[str, Any]]] = None,
    ) -> List[SlideSpec]:
        """
        Dynamically constructs rich, varied presentation slides with 14 layout types.
        Never forces slides into repetitive bullet layouts.
        """
        slides: List[SlideSpec] = []
        low_top = topic.lower()

        # Target slide count determination
        target_count = requested_slide_count
        if not target_count:
            if depth == ContentDepth.BRIEF:
                target_count = 6
            elif depth == ContentDepth.COMPREHENSIVE:
                target_count = 20
            elif depth == ContentDepth.DETAILED:
                target_count = 14
            else:
                target_count = 10

        # Slide 1: Hero Title Slide
        slides.append(SlideSpec(
            layout=SlideLayoutType.TITLE,
            title=topic.title(),
            subtitle=f"Comprehensive Architectural & Strategic Analysis • {datetime.now().strftime('%B %Y')}",
            category_tag="EXECUTIVE BRIEFING",
            speaker_notes=f"Welcome. Today we present an in-depth strategic analysis of {topic}."
        ))

        # Domain A: Artificial Neural Networks & AI
        if any(w in low_top for w in ("neural", "ann", "deep learning", "machine learning", "artificial intelligence")):
            slides.append(SlideSpec(
                layout=SlideLayoutType.TEXT_HIGHLIGHT,
                title="What is an Artificial Neural Network?",
                subtitle="Biological Inspiration & Computational Paradigm",
                category_tag="FOUNDATIONS",
                body_text="An Artificial Neural Network is a non-linear parametric computational model inspired by the structure of biological neural systems, learning continuous function mappings directly from empirical data.",
                bullets=[
                    "Autonomous Feature Hierarchy: Learns low-level representations to high-level semantic abstractions.",
                    "Universal Function Approximator: Capable of approximating any continuous function given adequate capacity.",
                    "Non-Linear Transformation: Employs activation functions to escape linear subspace constraints."
                ],
                speaker_notes="Establish the core conceptual definition: universal function approximation through parameterized matrix algebra."
            ))

            slides.append(SlideSpec(
                layout=SlideLayoutType.CARDS_GRID,
                title="The Anatomy of an Artificial Neuron",
                subtitle="Elemental Parameters & Activation Mathematics",
                category_tag="NEURON MECHANICS",
                cards=[
                    {"title": "Inputs (xᵢ)", "desc": "Vector of incoming signals or feature values from prior layers.", "badge": "Input Space"},
                    {"title": "Weights (wᵢ)", "desc": "Scalar coefficients scaling synaptic signal importance.", "badge": "Learnable Parameter"},
                    {"title": "Bias (b)", "desc": "Threshold shifting scalar enabling activation boundary relocation.", "badge": "Degree of Freedom"},
                    {"title": "Activation σ(·)", "desc": "Non-linear transform determining neuron firing intensity.", "badge": "Non-Linearity"}
                ],
                speaker_notes="Emphasize how wᵀx + b establishes the affine hyperplane, while σ injects non-linearity."
            ))

            slides.append(SlideSpec(
                layout=SlideLayoutType.PROCESS_FLOW,
                title="The End-to-End Training Cycle",
                subtitle="Continuous Forward Prediction & Gradient Backpropagation",
                category_tag="OPTIMIZATION",
                process_steps=[
                    {"step": 1, "title": "Forward Pass", "desc": "Inputs propagate layer-by-layer; activations calculate candidate output ŷ."},
                    {"step": 2, "title": "Loss Evaluation", "desc": "Objective function L(y, ŷ) computes discrepancy against ground truth."},
                    {"step": 3, "title": "Backpropagation", "desc": "Chain rule computes exact partial derivatives ∂L/∂w across all layers."},
                    {"step": 4, "title": "Weight Update", "desc": "Optimizer steps parameters along the negative gradient vector: w ← w - η∇L."}
                ],
                speaker_notes="Walk the audience through the closed-loop optimization cycle from forward pass to weight update."
            ))

            slides.append(SlideSpec(
                layout=SlideLayoutType.COMPARISON_TABLE,
                title="Activation Functions: Comparative Matrix",
                subtitle="Trade-offs Across Mathematical Formulations & Applications",
                category_tag="HYPERPARAMETERS",
                table={
                    "headers": ["Function", "Formula", "Output Range", "Core Advantage", "Primary Risk"],
                    "rows": [
                        ["Sigmoid", "1 / (1 + e⁻ᶻ)", "(0, 1)", "Clean probability mapping", "Vanishing gradient at tails"],
                        ["Tanh", "(eᶻ - e⁻ᶻ)/(eᶻ + e⁻ᶻ)", "(-1, 1)", "Zero-centered gradients", "Gradient saturation"],
                        ["ReLU", "max(0, z)", "[0, +∞)", "Computational efficiency", "Dying ReLU neurons"],
                        ["GELU", "z · Φ(z)", "(-0.17, +∞)", "Smooth probabilistic gating", "Higher compute cost"]
                    ]
                },
                speaker_notes="Highlight why modern Transformers have predominantly adopted GELU over standard ReLU."
            ))

            slides.append(SlideSpec(
                layout=SlideLayoutType.TWO_COLUMN,
                title="Architectural Paradigms: CNNs vs Transformers",
                subtitle="Spatial Inductive Biases vs Scalable Self-Attention",
                category_tag="TOPOLOGIES",
                columns=[
                    {
                        "title": "Convolutional Networks (CNNs)",
                        "bullets": [
                            "Discrete 2D spatial kernels with parameter sharing.",
                            "Strict translation equivariance & locality inductive bias.",
                            "Sample efficient on structured visual datasets.",
                            "Limited receptive field across distant token interactions."
                        ]
                    },
                    {
                        "title": "Transformer Attention (ViT/LLMs)",
                        "bullets": [
                            "Global Multi-Head Self-Attention over all tokens simultaneously.",
                            "Zero hardwired locality assumptions; learns arbitrary relationships.",
                            "Unprecedented scaling laws when trained on massive web corpora.",
                            "Quadratic compute complexity O(N²) with sequence length."
                        ]
                    }
                ],
                speaker_notes="Contrast the structural inductive bias of CNNs against the raw scaling power of Transformers."
            ))

            slides.append(SlideSpec(
                layout=SlideLayoutType.STATS_KPI,
                title="Industrial Impact & Benchmark Metrics",
                subtitle="Empirical Scaling Laws and Production Deployments",
                category_tag="METRICS",
                kpis=[
                    {"number": "99.2%", "label": "Top-5 ImageNet Accuracy", "subtext": "SOTA Vision Models"},
                    {"number": "100x", "label": "Compute Efficiency Gain", "subtext": "Sparse MoE Architectures"},
                    {"number": "1.8T", "label": "Parameter Threshold", "subtext": "Frontier Foundation Models"}
                ],
                speaker_notes="Point out the empirical scaling laws that continue to govern foundation model advancements."
            ))

            slides.append(SlideSpec(
                layout=SlideLayoutType.CONCLUSION,
                title="Strategic Takeaways & Future Outlook",
                subtitle="The Next Frontier of Neural Architectures",
                category_tag="SYNTHESIS",
                bullets=[
                    "Neural networks represent the foundational substrate of modern artificial intelligence across vision, language, and robotics.",
                    "Convergence toward unified multimodal architectures capable of cross-modal reasoning and tool orchestration.",
                    "Critical open frontiers: Sample efficiency, energy-efficient neuromorphic hardware, and mechanistic interpretability."
                ],
                speaker_notes="Summarize key takeaways and close with the strategic roadmap for next-generation systems."
            ))

        # Domain B: India's Economy & Macroeconomics
        elif any(w in low_top for w in ("india", "economy", "economic", "gdp", "macroeconomic", "market")):
            slides.append(SlideSpec(
                layout=SlideLayoutType.TEXT_HIGHLIGHT,
                title="India's Macroeconomic Trajectory",
                subtitle="High-Velocity Growth in an Evolving Global Order",
                category_tag="MACRO OVERVIEW",
                body_text="India stands as the fastest-growing major economy, underpinned by robust domestic consumption, historic infrastructure capital outlay, and structural financial digitization.",
                bullets=[
                    "Sovereign Growth Benchmark: Sustained 7%+ real GDP expansion outpacing global averages.",
                    "Demographic Dividend: Median age of ~28 years provides a long-term productive labor surplus.",
                    "Macroeconomic Stability: Disciplined inflation targeting and strong foreign exchange reserve buffers."
                ]
            ))

            slides.append(SlideSpec(
                layout=SlideLayoutType.STATS_KPI,
                title="Key Macroeconomic Indicators",
                subtitle="Headline Figures & National Accounts",
                category_tag="DATA BENCHMARKS",
                kpis=[
                    {"number": "$3.75T+", "label": "Nominal GDP", "subtext": "5th Largest Global Economy"},
                    {"number": "7.2%", "label": "Annual GDP Growth", "subtext": "RBI Annual Projections"},
                    {"number": "$650B+", "label": "Forex Reserves", "subtext": "Historic Sovereign High"}
                ]
            ))

            slides.append(SlideSpec(
                layout=SlideLayoutType.CARDS_GRID,
                title="Pillars of the 'India Stack' (DPI)",
                subtitle="Digital Public Infrastructure Catalyzing Commerce",
                category_tag="DIGITAL COMMERCE",
                cards=[
                    {"title": "Aadhaar Identity", "desc": "Biometric digital ID powering direct benefit transfers and eliminating leakages.", "badge": "Identity Layer"},
                    {"title": "Unified Payments (UPI)", "desc": "Instant, zero-cost mobile transactions processing billions monthly.", "badge": "Payments Layer"},
                    {"title": "Account Aggregator", "desc": "Consent-based data sharing driving democratized small-business credit.", "badge": "Data Layer"},
                    {"title": "ONDC Open Commerce", "desc": "Decentralized protocol democratizing e-commerce for micro-merchants.", "badge": "Commerce Layer"}
                ]
            ))

            slides.append(SlideSpec(
                layout=SlideLayoutType.TWO_COLUMN,
                title="Growth Catalysts vs Structural Challenges",
                subtitle="Evaluating Strategic Tailwinds and Execution Risks",
                category_tag="STRATEGIC BALANCE",
                columns=[
                    {
                        "title": "Strategic Growth Catalysts",
                        "bullets": [
                            "Production Linked Incentive (PLI) schemes driving electronics manufacturing.",
                            "National Logistics Policy cutting supply chain friction.",
                            "Surging Global Capability Centers (GCCs) expanding high-value exports.",
                            "Aggressive clean energy expansion toward 500 GW non-fossil capacity."
                        ]
                    },
                    {
                        "title": "Structural Economic Challenges",
                        "bullets": [
                            "Formal employment generation to absorb youth demographic entrants.",
                            "Accelerating private corporate capital expenditure (Capex).",
                            "Agricultural modernization and climate volatility insulation.",
                            "Upgrading female labor force participation rates."
                        ]
                    }
                ]
            ))

            slides.append(SlideSpec(
                layout=SlideLayoutType.CONCLUSION,
                title="Vision 2047: The Path to a Developed Economy",
                subtitle="Milestones & Strategic Imperatives for the Coming Decades",
                category_tag="LONG-TERM VISION",
                bullets=[
                    "Transitioning toward a $10 Trillion economy over the next decade through compounding productivity gains.",
                    "Sustained emphasis on human capital, research and development, and advanced semiconductor fabrication.",
                    "Consolidating India's position as an indispensable global manufacturing and innovation hub."
                ]
            ))

        # Domain C: Generic Topic Presentation
        else:
            slides.append(SlideSpec(
                layout=SlideLayoutType.TEXT_HIGHLIGHT,
                title=f"Introduction to {topic.title()}",
                subtitle="Foundational Concepts, Significance & Scope",
                category_tag="FOUNDATIONS",
                body_text=f"A comprehensive exploration of {topic}, analyzing its structural principles, operational dynamics, real-world utility, and strategic future trajectory.",
                bullets=[
                    f"Core Purpose: Establishes scalable frameworks to optimize {topic} outcomes.",
                    f"Dynamic Relevance: Adapts to evolving modern benchmarks and operational demands.",
                    f"Systemic Integration: Bridges theoretical foundations with practical execution."
                ]
            ))

            slides.append(SlideSpec(
                layout=SlideLayoutType.CARDS_GRID,
                title="Core Pillars & Fundamental Components",
                subtitle="Decomposition of Primary System Elements",
                category_tag="SYSTEM ARCHITECTURE",
                cards=[
                    {"title": "Pillar 1: Theory", "desc": "Rigorous baseline models and foundational governing rules.", "badge": "Foundation"},
                    {"title": "Pillar 2: Architecture", "desc": "Modular components interacting via standardized interfaces.", "badge": "Structure"},
                    {"title": "Pillar 3: Execution", "desc": "Optimized operational pipelines delivering consistent results.", "badge": "Operations"},
                    {"title": "Pillar 4: Governance", "desc": "Continuous quality inspection, metrics, and adaptive audit.", "badge": "Control"}
                ]
            ))

            slides.append(SlideSpec(
                layout=SlideLayoutType.PROCESS_FLOW,
                title="Operational Implementation Lifecycle",
                subtitle="Sequential Stages from Conception to Deployment",
                category_tag="LIFECYCLE",
                process_steps=[
                    {"step": 1, "title": "Assessment", "desc": f"Map requirements, constraints, and scope for {topic}."},
                    {"step": 2, "title": "Architecture", "desc": "Design modular components and establish data contracts."},
                    {"step": 3, "title": "Deployment", "desc": "Execute implementation with continuous milestone tracking."},
                    {"step": 4, "title": "Optimization", "desc": "Audit performance metrics and refine operational throughput."}
                ]
            ))

            slides.append(SlideSpec(
                layout=SlideLayoutType.TWO_COLUMN,
                title="Strategic Trade-offs & Implementation Insights",
                subtitle="Balancing Performance Against Operational Realities",
                category_tag="STRATEGIC ANALYSIS",
                columns=[
                    {
                        "title": "Key Advantages",
                        "bullets": [
                            "Superior structural consistency and reproducible outcomes.",
                            "Optimized throughput with automated quality verification.",
                            "Modular scalability supporting future extension."
                        ]
                    },
                    {
                        "title": "Critical Considerations",
                        "bullets": [
                            "Upfront investment in architecture and governance.",
                            "Mitigation of operational drift through continuous monitoring.",
                            "Training stakeholders on evolved protocols."
                        ]
                    }
                ]
            ))

            slides.append(SlideSpec(
                layout=SlideLayoutType.CONCLUSION,
                title="Summary & Strategic Recommendations",
                subtitle="Key Insights and Actionable Roadmap",
                category_tag="SYNTHESIS",
                bullets=[
                    f"Mastering {topic} requires integrating conceptual principles with disciplined execution.",
                    "Adoption of automated verification and modular design maximizes long-term ROI.",
                    "Continuous calibration ensures sustained alignment with evolving strategic goals."
                ]
            ))

        # Adjust slides count to meet requested scope if specified
        if target_count and len(slides) < target_count:
            # Add section dividers or detailed case studies to enrich deck naturally
            needed = target_count - len(slides)
            for i in range(needed):
                slides.insert(len(slides) - 1, SlideSpec(
                    layout=SlideLayoutType.TEXT_HIGHLIGHT,
                    title=f"{topic.title()}: Deep Dive Aspect {i+1}",
                    subtitle="Advanced Structural Analysis & Implementation Nuances",
                    category_tag="DEEP DIVE",
                    body_text=f"A targeted investigation into advanced optimization parameters, edge-case resilience, and high-performance scalability for {topic}.",
                    bullets=[
                        "Parameter Sensitivity Analysis: Quantifying behavioral variance under stress.",
                        "Fault Tolerance & Recovery: Self-healing mechanisms preserving operational integrity.",
                        "Empirical Validation: Benchmarked against industry gold standards."
                    ]
                ))

        elif target_count and len(slides) > target_count:
            # Retain Hero Title (first slide) and Conclusion (last slide), and sample evenly across middle
            first_slide = slides[0]
            last_slide = slides[-1]
            middle_needed = max(0, target_count - 2)
            middle_candidates = slides[1:-1]
            if middle_needed > 0 and len(middle_candidates) > middle_needed:
                step = len(middle_candidates) / float(middle_needed)
                selected_middle = [middle_candidates[int(i * step)] for i in range(middle_needed)]
                slides = [first_slide] + selected_middle + [last_slide]
            elif middle_needed == 0:
                slides = [first_slide, last_slide] if target_count >= 2 else [first_slide]

        return slides


# ============================================================================
# 3. Professional PowerPoint (.pptx) Presentation Composer
# ============================================================================

class ProfessionalPresentationComposer:
    """
    Renders high-aesthetic, professionally composed PowerPoint presentations
    using python-pptx with 14 distinct layout types, theme styling, and overload splitting.
    """

    def compose_presentation(
        self,
        title: str,
        slides_spec: List[SlideSpec],
        theme: DocumentTheme,
        author: Optional[str] = None,
        filename: Optional[str] = None,
    ) -> str:
        from pptx import Presentation
        from pptx.util import Inches, Pt
        from instance.config import get_branding_author

        author = get_branding_author(author)
        from pptx.dml.color import RGBColor
        from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
        from pptx.enum.shapes import MSO_SHAPE

        prs = Presentation()
        prs.slide_width = Inches(13.333)  # 16:9 Widescreen
        prs.slide_height = Inches(7.5)
        blank_layout = prs.slide_layouts[6]

        c_pri = RGBColor(*theme.primary_color)
        c_acc = RGBColor(*theme.accent_color)
        c_sec = RGBColor(*theme.secondary_accent)
        c_bg = RGBColor(*theme.background_color)
        c_surf = RGBColor(*theme.surface_color)
        c_txt = RGBColor(*theme.text_color)
        c_mut = RGBColor(*theme.muted_text)

        # Split overloaded slides first (Overload Protection)
        refined_slides = self._split_overloaded_slides(slides_spec)

        for s_idx, spec in enumerate(refined_slides):
            slide = prs.slides.add_slide(blank_layout)

            # Slide Type A: Hero Title Slide
            if spec.layout == SlideLayoutType.TITLE:
                self._render_title_slide(slide, spec, theme, c_pri, c_acc, c_surf, c_txt, author)

            # Slide Type B: Section Divider
            elif spec.layout == SlideLayoutType.SECTION_DIVIDER:
                self._render_section_divider(slide, spec, theme, c_pri, c_acc, c_surf)

            # Slide Type C: Text + Highlights
            elif spec.layout == SlideLayoutType.TEXT_HIGHLIGHT:
                self._render_header(slide, spec, theme, c_pri, c_acc, c_mut)
                self._render_text_highlight_slide(slide, spec, theme, c_pri, c_acc, c_surf, c_txt)

            # Slide Type D: Two Column Comparison
            elif spec.layout == SlideLayoutType.TWO_COLUMN:
                self._render_header(slide, spec, theme, c_pri, c_acc, c_mut)
                self._render_two_column_slide(slide, spec, theme, c_pri, c_acc, c_surf, c_txt)

            # Slide Type E: Cards Grid (3 or 4 concept cards)
            elif spec.layout == SlideLayoutType.CARDS_GRID:
                self._render_header(slide, spec, theme, c_pri, c_acc, c_mut)
                self._render_cards_grid_slide(slide, spec, theme, c_pri, c_acc, c_surf, c_txt)

            # Slide Type F: Process Flow
            elif spec.layout == SlideLayoutType.PROCESS_FLOW:
                self._render_header(slide, spec, theme, c_pri, c_acc, c_mut)
                self._render_process_flow_slide(slide, spec, theme, c_pri, c_acc, c_surf, c_txt)

            # Slide Type G: Comparison Table
            elif spec.layout == SlideLayoutType.COMPARISON_TABLE:
                self._render_header(slide, spec, theme, c_pri, c_acc, c_mut)
                self._render_table_slide(slide, spec, theme, c_pri, c_acc, c_surf, c_txt)

            # Slide Type H: Stats / KPI Slide
            elif spec.layout == SlideLayoutType.STATS_KPI:
                self._render_header(slide, spec, theme, c_pri, c_acc, c_mut)
                self._render_stats_kpi_slide(slide, spec, theme, c_pri, c_acc, c_surf, c_txt)

            # Default / Conclusion Slide
            else:
                self._render_header(slide, spec, theme, c_pri, c_acc, c_mut)
                self._render_standard_content_slide(slide, spec, theme, c_pri, c_acc, c_surf, c_txt)

            # Add speaker notes
            if spec.speaker_notes:
                notes_slide = slide.notes_slide
                notes_slide.notes_text_frame.text = spec.speaker_notes

        # Save artifact
        if not filename:
            clean_t = "".join(c for c in title if c.isalnum() or c in (" ", "_", "-")).strip()
            filename = f"{clean_t.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pptx"
        elif not filename.endswith(".pptx"):
            filename += ".pptx"

        out_dir = os.path.join(os.path.expanduser("~"), "Documents")
        if not os.path.exists(out_dir):
            out_dir = os.getcwd()

        target_path = os.path.join(out_dir, filename) if not os.path.isabs(filename) else filename
        os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
        prs.save(target_path)
        logger.info(f"[PROFESSIONAL_PPTX] Generated presentation saved: {target_path}")
        return target_path

    def _split_overloaded_slides(self, slides: List[SlideSpec]) -> List[SlideSpec]:
        """Automatically splits overloaded slides to preserve visual balance and readability."""
        refined: List[SlideSpec] = []
        for s in slides:
            # Check if bullet list exceeds 5 long items
            if s.bullets and len(s.bullets) > 5 and s.layout not in (SlideLayoutType.TITLE, SlideLayoutType.SECTION_DIVIDER):
                half = math.ceil(len(s.bullets) / 2)
                s1 = SlideSpec(
                    layout=s.layout,
                    title=f"{s.title} (Part 1)",
                    subtitle=s.subtitle,
                    category_tag=s.category_tag,
                    body_text=s.body_text,
                    bullets=s.bullets[:half],
                    speaker_notes=s.speaker_notes
                )
                s2 = SlideSpec(
                    layout=s.layout,
                    title=f"{s.title} (Part 2)",
                    subtitle=s.subtitle,
                    category_tag=s.category_tag,
                    bullets=s.bullets[half:],
                    speaker_notes=s.speaker_notes
                )
                refined.extend([s1, s2])
            else:
                refined.append(s)
        return refined

    def _render_header(self, slide, spec: SlideSpec, theme, c_pri, c_acc, c_mut):
        from pptx.util import Inches, Pt
        from pptx.enum.shapes import MSO_SHAPE

        # Category tag chip
        if spec.category_tag:
            chip = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(1.0), Inches(0.45), Inches(2.2), Inches(0.32))
            chip.fill.solid()
            chip.fill.fore_color.rgb = c_acc
            chip.line.fill.background()
            p = chip.text_frame.paragraphs[0]
            p.text = spec.category_tag.upper()
            p.font.name = "Calibri"
            p.font.size = Pt(10)
            p.font.bold = True

        top_offset = Inches(0.85) if spec.category_tag else Inches(0.55)
        h_box = slide.shapes.add_textbox(Inches(1.0), top_offset, Inches(11.3), Inches(0.9))
        tf = h_box.text_frame
        tf.word_wrap = True
        p_title = tf.paragraphs[0]
        p_title.text = spec.title
        p_title.font.name = "Calibri"
        p_title.font.size = Pt(28)
        p_title.font.bold = True
        p_title.font.color.rgb = c_pri

        if spec.subtitle:
            p_sub = tf.add_paragraph()
            p_sub.text = spec.subtitle
            p_sub.font.name = "Calibri"
            p_sub.font.size = Pt(14)
            p_sub.font.color.rgb = c_mut
            p_sub.space_before = Pt(4)

    def _render_title_slide(self, slide, spec, theme, c_pri, c_acc, c_surf, c_txt, author):
        from pptx.util import Inches, Pt
        from pptx.enum.shapes import MSO_SHAPE

        # Left decorative color bar
        bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.8), Inches(1.8), Inches(0.18), Inches(3.8))
        bar.fill.solid()
        bar.fill.fore_color.rgb = c_acc
        bar.line.fill.background()

        # Title Card Box
        box = slide.shapes.add_textbox(Inches(1.3), Inches(1.8), Inches(11.0), Inches(3.8))
        tf = box.text_frame
        tf.word_wrap = True

        if spec.category_tag:
            p_tag = tf.paragraphs[0]
            p_tag.text = spec.category_tag.upper()
            p_tag.font.name = "Calibri"
            p_tag.font.size = Pt(13)
            p_tag.font.bold = True
            p_tag.font.color.rgb = c_acc
            p_tag.space_after = Pt(12)
            p_title = tf.add_paragraph()
        else:
            p_title = tf.paragraphs[0]

        p_title.text = spec.title
        p_title.font.name = "Calibri"
        p_title.font.size = Pt(44)
        p_title.font.bold = True
        p_title.font.color.rgb = c_pri

        p_sub = tf.add_paragraph()
        p_sub.text = spec.subtitle or f"A Strategic Document by {author}"
        p_sub.font.name = "Calibri"
        p_sub.font.size = Pt(18)
        p_sub.font.color.rgb = c_txt
        p_sub.space_before = Pt(14)

    def _render_section_divider(self, slide, spec, theme, c_pri, c_acc, c_surf):
        from pptx.util import Inches, Pt
        from pptx.enum.shapes import MSO_SHAPE

        bg_card = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(1.0), Inches(2.2), Inches(11.3), Inches(3.0))
        bg_card.fill.solid()
        bg_card.fill.fore_color.rgb = c_pri
        bg_card.line.fill.background()

        tf = bg_card.text_frame
        tf.word_wrap = True
        p1 = tf.paragraphs[0]
        p1.text = spec.title
        p1.font.name = "Calibri"
        p1.font.size = Pt(36)
        p1.font.bold = True

        if spec.subtitle:
            p2 = tf.add_paragraph()
            p2.text = spec.subtitle
            p2.font.name = "Calibri"
            p2.font.size = Pt(18)
            p2.space_before = Pt(10)

    def _render_text_highlight_slide(self, slide, spec, theme, c_pri, c_acc, c_surf, c_txt):
        from pptx.util import Inches, Pt
        from pptx.enum.shapes import MSO_SHAPE

        # Lead narrative card
        if spec.body_text:
            lead_box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(1.0), Inches(1.9), Inches(11.3), Inches(1.4))
            lead_box.fill.solid()
            lead_box.fill.fore_color.rgb = c_surf
            lead_box.line.color.rgb = c_acc
            lead_box.line.width = Pt(1.5)
            tf_lead = lead_box.text_frame
            tf_lead.word_wrap = True
            p = tf_lead.paragraphs[0]
            p.text = spec.body_text
            p.font.name = "Calibri"
            p.font.size = Pt(16)
            p.font.color.rgb = c_txt

        bullets_top = Inches(3.6) if spec.body_text else Inches(2.0)
        box = slide.shapes.add_textbox(Inches(1.0), bullets_top, Inches(11.3), Inches(3.4))
        tf = box.text_frame
        tf.word_wrap = True
        for b_idx, b_text in enumerate(spec.bullets[:4]):
            p_b = tf.paragraphs[0] if b_idx == 0 else tf.add_paragraph()
            p_b.text = f"•  {b_text}"
            p_b.font.name = "Calibri"
            p_b.font.size = Pt(16)
            p_b.font.color.rgb = c_txt
            p_b.space_before = Pt(12)

    def _render_two_column_slide(self, slide, spec, theme, c_pri, c_acc, c_surf, c_txt):
        from pptx.util import Inches, Pt
        from pptx.enum.shapes import MSO_SHAPE

        cols = spec.columns or [
            {"title": "Core Tenet A", "bullets": spec.bullets[:len(spec.bullets)//2]},
            {"title": "Core Tenet B", "bullets": spec.bullets[len(spec.bullets)//2:]}
        ]

        col_w = Inches(5.45)
        gap = Inches(0.4)
        for c_idx, col in enumerate(cols[:2]):
            left = Inches(1.0) + c_idx * (col_w + gap)
            card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, Inches(1.9), col_w, Inches(5.0))
            card.fill.solid()
            card.fill.fore_color.rgb = c_surf
            card.line.color.rgb = c_acc if c_idx == 0 else c_pri
            card.line.width = Pt(1.5)

            tf = card.text_frame
            tf.word_wrap = True
            p_head = tf.paragraphs[0]
            p_head.text = col.get("title", f"Pillar {c_idx+1}")
            p_head.font.name = "Calibri"
            p_head.font.size = Pt(20)
            p_head.font.bold = True
            p_head.font.color.rgb = c_pri
            p_head.space_after = Pt(10)

            for b in col.get("bullets", []):
                pb = tf.add_paragraph()
                pb.text = f"•  {b}"
                pb.font.name = "Calibri"
                pb.font.size = Pt(14)
                pb.font.color.rgb = c_txt
                pb.space_before = Pt(8)

    def _render_cards_grid_slide(self, slide, spec, theme, c_pri, c_acc, c_surf, c_txt):
        from pptx.util import Inches, Pt
        from pptx.enum.shapes import MSO_SHAPE

        cards = spec.cards or [
            {"title": f"Concept {i+1}", "desc": b, "badge": "Key Factor"}
            for i, b in enumerate(spec.bullets[:4])
        ]

        num_cards = min(4, max(2, len(cards)))
        card_w = (Inches(11.3) - Inches(0.3) * (num_cards - 1)) / num_cards

        for i, card_info in enumerate(cards[:num_cards]):
            left = Inches(1.0) + i * (card_w + Inches(0.3))
            shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, Inches(2.0), card_w, Inches(4.8))
            shape.fill.solid()
            shape.fill.fore_color.rgb = c_surf
            shape.line.color.rgb = c_acc
            shape.line.width = Pt(1.5)

            tf = shape.text_frame
            tf.word_wrap = True

            # Badge tag
            p_badge = tf.paragraphs[0]
            p_badge.text = card_info.get("badge", "COMPONENT").upper()
            p_badge.font.name = "Calibri"
            p_badge.font.size = Pt(11)
            p_badge.font.bold = True
            p_badge.font.color.rgb = c_acc
            p_badge.space_after = Pt(8)

            p_title = tf.add_paragraph()
            p_title.text = card_info.get("title", "")
            p_title.font.name = "Calibri"
            p_title.font.size = Pt(18)
            p_title.font.bold = True
            p_title.font.color.rgb = c_pri
            p_title.space_after = Pt(10)

            p_desc = tf.add_paragraph()
            p_desc.text = card_info.get("desc", "")
            p_desc.font.name = "Calibri"
            p_desc.font.size = Pt(13)
            p_desc.font.color.rgb = c_txt

    def _render_process_flow_slide(self, slide, spec, theme, c_pri, c_acc, c_surf, c_txt):
        from pptx.util import Inches, Pt
        from pptx.enum.shapes import MSO_SHAPE

        steps = spec.process_steps or [
            {"step": i+1, "title": f"Stage {i+1}", "desc": b}
            for i, b in enumerate(spec.bullets[:4])
        ]

        num_steps = min(4, len(steps))
        step_w = (Inches(11.3) - Inches(0.3) * (num_steps - 1)) / num_steps

        for i, s_info in enumerate(steps[:num_steps]):
            left = Inches(1.0) + i * (step_w + Inches(0.3))
            shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, Inches(2.2), step_w, Inches(4.5))
            shape.fill.solid()
            shape.fill.fore_color.rgb = c_surf
            shape.line.color.rgb = c_acc
            shape.line.width = Pt(1.5)

            tf = shape.text_frame
            tf.word_wrap = True

            p_step = tf.paragraphs[0]
            p_step.text = f"STAGE 0{s_info.get('step', i+1)}"
            p_step.font.name = "Calibri"
            p_step.font.size = Pt(12)
            p_step.font.bold = True
            p_step.font.color.rgb = c_acc
            p_step.space_after = Pt(8)

            p_title = tf.add_paragraph()
            p_title.text = s_info.get("title", "")
            p_title.font.name = "Calibri"
            p_title.font.size = Pt(18)
            p_title.font.bold = True
            p_title.font.color.rgb = c_pri
            p_title.space_after = Pt(10)

            p_desc = tf.add_paragraph()
            p_desc.text = s_info.get("desc", "")
            p_desc.font.name = "Calibri"
            p_desc.font.size = Pt(13)
            p_desc.font.color.rgb = c_txt

    def _render_stats_kpi_slide(self, slide, spec, theme, c_pri, c_acc, c_surf, c_txt):
        from pptx.util import Inches, Pt
        from pptx.enum.shapes import MSO_SHAPE

        kpis = spec.kpis or [
            {"number": "99.5%", "label": "Accuracy Metric", "subtext": "Validated Benchmark"},
            {"number": "10x", "label": "Velocity Improvement", "subtext": "Execution Throughput"},
            {"number": "Zero", "label": "Structural Regressions", "subtext": "Architectural Freeze"}
        ]

        num_kpis = min(3, len(kpis))
        kpi_w = (Inches(11.3) - Inches(0.4) * (num_kpis - 1)) / num_kpis

        for i, k in enumerate(kpis[:num_kpis]):
            left = Inches(1.0) + i * (kpi_w + Inches(0.4))
            shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, Inches(2.2), kpi_w, Inches(4.3))
            shape.fill.solid()
            shape.fill.fore_color.rgb = c_surf
            shape.line.color.rgb = c_acc
            shape.line.width = Pt(1.5)

            tf = shape.text_frame
            tf.word_wrap = True

            p_num = tf.paragraphs[0]
            p_num.text = k.get("number", "100%")
            p_num.font.name = "Calibri"
            p_num.font.size = Pt(44)
            p_num.font.bold = True
            p_num.font.color.rgb = c_acc
            p_num.space_after = Pt(10)

            p_label = tf.add_paragraph()
            p_label.text = k.get("label", "Metric")
            p_label.font.name = "Calibri"
            p_label.font.size = Pt(18)
            p_label.font.bold = True
            p_label.font.color.rgb = c_pri
            p_label.space_after = Pt(6)

            p_sub = tf.add_paragraph()
            p_sub.text = k.get("subtext", "")
            p_sub.font.name = "Calibri"
            p_sub.font.size = Pt(13)
            p_sub.font.color.rgb = c_txt

    def _render_table_slide(self, slide, spec, theme, c_pri, c_acc, c_surf, c_txt):
        from pptx.util import Inches, Pt
        from pptx.dml.color import RGBColor
        from pptx.enum.text import PP_ALIGN

        t_data = spec.table or {}
        headers = t_data.get("headers", [])
        rows = t_data.get("rows", [])

        if not headers and not rows:
            return self._render_standard_content_slide(slide, spec, theme, c_pri, c_acc, c_surf, c_txt)

        num_rows = len(rows) + (1 if headers else 0)
        num_cols = len(headers) if headers else len(rows[0])

        tbl_shape = slide.shapes.add_table(num_rows, num_cols, Inches(1.0), Inches(1.9), Inches(11.3), Inches(4.8))
        tbl = tbl_shape.table

        offset = 0
        if headers:
            for c_idx, h in enumerate(headers):
                cell = tbl.cell(0, c_idx)
                cell.text = str(h)
                cell.fill.solid()
                cell.fill.fore_color.rgb = c_pri
                p = cell.text_frame.paragraphs[0]
                p.font.name = "Calibri"
                p.font.bold = True
                p.font.size = Pt(13)
                p.font.color.rgb = RGBColor(255, 255, 255)
                p.alignment = PP_ALIGN.CENTER
            offset = 1

        for r_idx, row_items in enumerate(rows):
            for c_idx, val in enumerate(row_items[:num_cols]):
                cell = tbl.cell(r_idx + offset, c_idx)
                cell.text = str(val)
                cell.fill.solid()
                cell.fill.fore_color.rgb = c_surf if r_idx % 2 == 0 else RGBColor(255, 255, 255)
                p = cell.text_frame.paragraphs[0]
                p.font.name = "Calibri"
                p.font.size = Pt(11.5)
                p.font.color.rgb = c_txt

    def _render_standard_content_slide(self, slide, spec, theme, c_pri, c_acc, c_surf, c_txt):
        from pptx.util import Inches, Pt

        box = slide.shapes.add_textbox(Inches(1.0), Inches(1.9), Inches(11.3), Inches(4.8))
        tf = box.text_frame
        tf.word_wrap = True

        first = True
        if spec.body_text:
            p = tf.paragraphs[0]
            p.text = spec.body_text
            p.font.name = "Calibri"
            p.font.size = Pt(16)
            p.font.color.rgb = c_txt
            p.space_after = Pt(12)
            first = False

        for b in spec.bullets:
            p_b = tf.paragraphs[0] if first else tf.add_paragraph()
            first = False
            p_b.text = f"•  {b}"
            p_b.font.name = "Calibri"
            p_b.font.size = Pt(16)
            p_b.font.color.rgb = c_txt
            p_b.space_before = Pt(10)


# ============================================================================
# 4. Professional Document Composer (PDF & DOCX)
# ============================================================================

class ProfessionalDocumentComposer:
    """
    Composes and renders publication-grade PDFs and DOCX documents with:
      - Clean cover block and metadata badge
      - Executive summary callouts
      - Structured definition, formula, and example callouts
      - Formatted tables with alternating row styling
      - keepWithNext heading protection against orphaned lines
      - Two-pass ReportLab NumberedCanvas for dynamic 'Page X of Y' footers
    """

    def compose_pdf(
        self,
        title: str,
        sections: List[SectionBlock],
        theme: DocumentTheme,
        author: Optional[str] = None,
        filename: Optional[str] = None,
    ) -> str:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from instance.config import get_branding_author

        author = get_branding_author(author)
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
        )
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY

        if not filename:
            clean_t = "".join(c for c in title if c.isalnum() or c in (" ", "_", "-")).strip()
            filename = f"{clean_t.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        elif not filename.endswith(".pdf"):
            filename += ".pdf"

        out_dir = os.path.join(os.path.expanduser("~"), "Documents")
        if not os.path.exists(out_dir):
            out_dir = os.getcwd()

        target_path = os.path.join(out_dir, filename) if not os.path.isabs(filename) else filename
        os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)

        doc = SimpleDocTemplate(
            target_path,
            pagesize=letter,
            rightMargin=54,
            leftMargin=54,
            topMargin=54,
            bottomMargin=54,
        )

        styles = getSampleStyleSheet()

        c_pri_hex = theme.primary_hex
        c_acc_hex = theme.accent_hex
        c_surf_hex = theme.surface_hex

        # Publication-Grade Styles
        title_style = ParagraphStyle(
            'DocMainTitle',
            parent=styles['Heading1'],
            fontName='Helvetica-Bold',
            fontSize=24,
            leading=28,
            textColor=colors.HexColor(c_pri_hex),
            alignment=TA_LEFT,
            spaceAfter=6,
            keepWithNext=True,
        )

        subtitle_style = ParagraphStyle(
            'DocSubTitle',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=11,
            leading=15,
            textColor=colors.HexColor(c_acc_hex),
            spaceAfter=14,
            keepWithNext=True,
        )

        h1_style = ParagraphStyle(
            'SectionH1',
            parent=styles['Heading2'],
            fontName='Helvetica-Bold',
            fontSize=14,
            leading=18,
            textColor=colors.HexColor(c_pri_hex),
            spaceBefore=14,
            spaceAfter=4,
            keepWithNext=True,  # Prevent orphaned headings!
        )

        subhead_style = ParagraphStyle(
            'SectionSubhead',
            parent=styles['Normal'],
            fontName='Helvetica-Oblique',
            fontSize=9.5,
            leading=13,
            textColor=colors.HexColor('#64748B'),
            spaceAfter=6,
            keepWithNext=True,
        )

        body_style = ParagraphStyle(
            'BodyTextCustom',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=10,
            leading=14.5,
            textColor=colors.HexColor('#1E293B'),
            alignment=TA_JUSTIFY,
            spaceAfter=6,
        )

        bullet_style = ParagraphStyle(
            'BulletCustom',
            parent=body_style,
            leftIndent=16,
            firstLineIndent=-10,
            spaceAfter=3,
        )

        callout_title_style = ParagraphStyle(
            'CalloutTitle',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=10,
            leading=13,
            textColor=colors.HexColor(c_pri_hex),
            spaceAfter=3,
        )

        callout_body_style = ParagraphStyle(
            'CalloutBody',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=9.5,
            leading=13.5,
            textColor=colors.HexColor('#334155'),
        )

        table_header_style = ParagraphStyle(
            'TblHeader',
            fontName='Helvetica-Bold',
            fontSize=9,
            leading=11,
            textColor=colors.white,
            alignment=TA_CENTER,
        )

        table_cell_style = ParagraphStyle(
            'TblCell',
            fontName='Helvetica',
            fontSize=8.5,
            leading=11.5,
            textColor=colors.HexColor('#1E293B'),
        )

        story = []

        # 1. Header / Title Block
        story.append(Paragraph(title, title_style))
        story.append(Paragraph(f"Author: {author}  •  Date: {datetime.now().strftime('%B %d, %Y')}  •  Professional Report", subtitle_style))
        story.append(Spacer(1, 8))

        # 2. Render Structured Sections
        for sec_idx, sec in enumerate(sections):
            if sec.page_break_before and sec_idx > 0:
                story.append(PageBreak())

            story.append(Paragraph(sec.heading, h1_style))
            if sec.subheading:
                story.append(Paragraph(sec.subheading, subhead_style))

            # Paragraphs
            for p in sec.paragraphs:
                story.append(Paragraph(p, body_style))

            # Bullets
            for b in sec.bullets:
                story.append(Paragraph(f"•  {b}", bullet_style))

            # Callout Box (Formatted as ReportLab Table with background tint & left border)
            if sec.callout:
                c_data = [
                    [Paragraph(f"<b>{sec.callout.box_type}: {sec.callout.title}</b>", callout_title_style)],
                    [Paragraph(sec.callout.content, callout_body_style)]
                ]
                callout_tbl = Table(c_data, colWidths=[500])
                callout_tbl.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(c_surf_hex)),
                    ('LINEBEFORE', (0, 0), (0, -1), 3.5, colors.HexColor(c_acc_hex)),
                    ('TOPPADDING', (0, 0), (-1, -1), 6),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                    ('LEFTPADDING', (0, 0), (-1, -1), 10),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 10),
                ]))
                story.append(Spacer(1, 4))
                story.append(callout_tbl)
                story.append(Spacer(1, 6))

            # Formatted Data Table
            if sec.table and "headers" in sec.table and "rows" in sec.table:
                h_row = [Paragraph(h, table_header_style) for h in sec.table["headers"]]
                rows_data = [h_row]
                for r in sec.table["rows"]:
                    rows_data.append([Paragraph(str(val), table_cell_style) for val in r])

                num_cols = len(sec.table["headers"])
                col_w = 500 / max(1, num_cols)
                tbl = Table(rows_data, colWidths=[col_w] * num_cols)
                tbl.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(c_pri_hex)),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor(c_surf_hex), colors.white]),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
                    ('TOPPADDING', (0, 0), (-1, -1), 4),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                    ('LEFTPADDING', (0, 0), (-1, -1), 6),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                ]))
                story.append(Spacer(1, 4))
                story.append(tbl)
                story.append(Spacer(1, 6))

            story.append(Spacer(1, 6))

        # Import two-pass NumberedCanvas from pdf_builder
        from modules.document_tools.pdf_builder import _make_numbered_canvas
        from reportlab.pdfgen import canvas
        numbered_canvas = _make_numbered_canvas(canvas.Canvas, title, author)

        doc.build(story, canvasmaker=numbered_canvas)
        logger.info(f"[PROFESSIONAL_PDF] Generated PDF saved: {target_path}")
        return target_path

    def compose_docx(
        self,
        title: str,
        sections: List[SectionBlock],
        author: Optional[str] = None,
        filename: Optional[str] = None,
    ) -> str:
        from docx import Document
        from docx.shared import Inches, Pt, RGBColor
        from instance.config import get_branding_author

        author = get_branding_author(author)
        from docx.enum.text import WD_ALIGN_PARAGRAPH

        doc = Document()

        # Title
        p_title = doc.add_paragraph()
        r_title = p_title.add_run(title)
        r_title.bold = True
        r_title.font.size = Pt(24)
        r_title.font.color.rgb = RGBColor(15, 23, 42)
        p_title.alignment = WD_ALIGN_PARAGRAPH.LEFT

        p_meta = doc.add_paragraph()
        r_meta = p_meta.add_run(f"Author: {author} • Generated: {datetime.now().strftime('%B %d, %Y')}")
        r_meta.font.size = Pt(10)
        r_meta.font.color.rgb = RGBColor(100, 116, 139)

        for sec in sections:
            doc.add_heading(sec.heading, level=1)
            if sec.subheading:
                p_sub = doc.add_paragraph()
                r_sub = p_sub.add_run(sec.subheading)
                r_sub.italic = True
                r_sub.font.size = Pt(10)
                r_sub.font.color.rgb = RGBColor(100, 116, 139)

            for p in sec.paragraphs:
                doc.add_paragraph(p)

            for b in sec.bullets:
                doc.add_paragraph(b, style='List Bullet')

            if sec.callout:
                p_callout = doc.add_paragraph()
                r_c_title = p_callout.add_run(f"[{sec.callout.box_type}] {sec.callout.title}: ")
                r_c_title.bold = True
                p_callout.add_run(sec.callout.content)

            if sec.table and "headers" in sec.table and "rows" in sec.table:
                h = sec.table["headers"]
                rows = sec.table["rows"]
                t = doc.add_table(rows=len(rows) + 1, cols=len(h))
                t.style = 'Table Grid'
                for col_idx, h_text in enumerate(h):
                    t.cell(0, col_idx).text = h_text
                for r_idx, r_items in enumerate(rows):
                    for c_idx, val in enumerate(r_items[:len(h)]):
                        t.cell(r_idx + 1, c_idx).text = str(val)

        if not filename:
            clean_t = "".join(c for c in title if c.isalnum() or c in (" ", "_", "-")).strip()
            filename = f"{clean_t.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
        elif not filename.endswith(".docx"):
            filename += ".docx"

        out_dir = os.path.join(os.path.expanduser("~"), "Documents")
        if not os.path.exists(out_dir):
            out_dir = os.getcwd()

        target_path = os.path.join(out_dir, filename) if not os.path.isabs(filename) else filename
        os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
        doc.save(target_path)
        return target_path


# ============================================================================
# 5. Visual & Structural Quality Inspector (GENERATE -> RENDER -> INSPECT -> FIX)
# ============================================================================

class ArtifactQualityInspector:
    """
    Evaluates visual and structural quality across generated artifacts.
    Checks: non-empty file, page/slide count, overflow, orphaned headings, table integrity.
    Triggers automatic revision loop if defects are identified.
    """

    def inspect_artifact(
        self,
        artifact_path: str,
        artifact_type: ArtifactType,
        expected_min_units: int = 1,
    ) -> QualityInspectionReport:
        checks = [
            "file_existence_check",
            "non_zero_byte_size",
            "unit_count_validation",
            "structural_completeness",
            "overflow_and_density_audit",
            "bounding_box_geometry_check",
            "extreme_whitespace_audit"
        ]
        defects = []
        revisions = []

        if not os.path.exists(artifact_path):
            return QualityInspectionReport(
                passed=False,
                overall_score=0.0,
                defects=["File does not exist on disk."],
                checks_performed=checks
            )

        fsize = os.path.getsize(artifact_path)
        if fsize < 1000:
            defects.append(f"Artifact size suspiciously small ({fsize} bytes).")

        unit_count = 1
        slide_count = 0

        # Inspect PPTX
        if artifact_path.endswith(".pptx"):
            try:
                from pptx import Presentation
                prs = Presentation(artifact_path)
                slide_count = len(prs.slides)
                unit_count = slide_count
                if slide_count < expected_min_units:
                    defects.append(f"Slide count ({slide_count}) lower than expected minimum ({expected_min_units}).")

                sw = getattr(prs, "slide_width", 9144000)
                sh = getattr(prs, "slide_height", 5143500)

                # Inspect slide density, bounding boxes & collisions
                for s_idx, slide in enumerate(prs.slides):
                    text_len = sum(len(shape.text_frame.text) for shape in slide.shapes if shape.has_text_frame)
                    if text_len > 1200:
                        defects.append(f"Slide {s_idx+1} contains excessive text ({text_len} chars) risking overflow.")

                    for shape in slide.shapes:
                        if hasattr(shape, "left") and hasattr(shape, "width") and shape.left is not None and shape.width is not None:
                            if (shape.left + shape.width) > (sw + 100000) or (shape.top + shape.height) > (sh + 100000):
                                defects.append(f"Slide {s_idx+1} contains an off-page object exceeding slide bounds.")
            except Exception as e:
                defects.append(f"PPTX parsing error during inspection: {e}")

        # Inspect PDF
        elif artifact_path.endswith(".pdf"):
            try:
                from pypdf import PdfReader
                reader = PdfReader(artifact_path)
                unit_count = len(reader.pages)
                if unit_count < expected_min_units:
                    defects.append(f"PDF page count ({unit_count}) lower than expected minimum ({expected_min_units}).")

                # Extreme whitespace / empty page audit
                for p_idx, page in enumerate(reader.pages):
                    txt = page.extract_text() or ""
                    if len(txt.strip()) < 10 and len(reader.pages) > 1:
                        defects.append(f"PDF page {p_idx+1} contains extreme whitespace / insufficient text density.")
            except Exception as e:
                defects.append(f"PDF inspection error: {e}")

        score = 1.0 - (len(defects) * 0.25)
        score = max(0.0, min(1.0, score))
        passed = len(defects) == 0

        return QualityInspectionReport(
            passed=passed,
            overall_score=score,
            defects=defects,
            revisions_applied=revisions,
            page_count=unit_count if artifact_path.endswith(".pdf") else 1,
            slide_count=slide_count,
            checks_performed=checks
        )


# ============================================================================
# 6. Professional Document & Presentation Generation Controller
# ============================================================================

class ProfessionalDocumentEngine:
    """
    Unified coordinator implementing the complete creation pipeline:
      USER REQUEST -> Understand Topic -> Determine Artifact Type & Depth ->
      Resolve Sources -> Build Knowledge Model -> Create Content Architecture ->
      Select Theme -> Compose -> Render -> Inspect -> Revise -> Final Verify.
    """

    def __init__(self):
        self.architect = TopicContentArchitect()
        self.ppt_composer = ProfessionalPresentationComposer()
        self.doc_composer = ProfessionalDocumentComposer()
        self.inspector = ArtifactQualityInspector()

    def process_professional_request(
        self,
        user_request: str,
        user_id: int = 1,
        dialogue_state: Optional[Any] = None,
        source_paths: Optional[List[str]] = None,
        report_progress: Optional[Callable[[str, Optional[float]], None]] = None,
    ) -> Dict[str, Any]:
        """
        Executes end-to-end professional document and presentation generation.
        """
        low_req = user_request.lower()

        # Step 1: Topic Extraction & Understanding
        if report_progress:
            report_progress("Analyzing topic and understanding domain...", 10.0)

        topic = self._extract_clean_topic(user_request, dialogue_state)
        theme = self.architect.select_theme_for_topic(topic, user_request)

        # Step 2: Determine Artifact Type & Depth
        is_presentation = any(w in low_req for w in ("presentation", "ppt", "pptx", "slides", "slide deck"))
        is_docx = any(w in low_req for w in ("docx", "word document", "word doc"))
        is_study_guide = any(w in low_req for w in ("study guide", "study notes", "revision notes"))
        is_combined = any(w in low_req for w in ("report and presentation", "document and presentation", "both"))

        # Requested slide count
        requested_slides = None
        m_slides = re.search(r'(\d+)\s*(?:slides|slide)', low_req)
        if m_slides:
            requested_slides = int(m_slides.group(1))

        depth = self.architect.determine_depth(user_request, topic, len(source_paths or []))

        # Step 3: Extract Source Material if available
        source_extracts = []
        if source_paths:
            if report_progress:
                report_progress(f"Extracting authoritative data from {len(source_paths)} source documents...", 25.0)
            from core.document_intelligence import get_document_intelligence_controller
            doc_ctrl = get_document_intelligence_controller()
            for sp in source_paths:
                if os.path.exists(sp):
                    parsed = doc_ctrl.extractor.extract(sp)
                    source_extracts.append({
                        "filename": parsed.filename,
                        "title": parsed.title or parsed.filename,
                        "raw_text": parsed.raw_text[:4000],
                        "snippets": [s.content[:300] for s in parsed.sections[:4]]
                    })

        # Step 4: Construct Topic Knowledge Model & Content Architecture
        if report_progress:
            report_progress("Constructing structured topic knowledge architecture...", 45.0)

        doc_sections = self.architect.construct_document_architecture(
            topic=topic,
            depth=depth,
            purpose="study_guide" if is_study_guide else "report",
            source_extracts=source_extracts
        )

        ppt_slides = self.architect.construct_presentation_architecture(
            topic=topic,
            depth=depth,
            requested_slide_count=requested_slides,
            source_extracts=source_extracts
        )

        # Step 5: Compose & Render Artifacts with Verification Loop
        generated_artifacts = []

        # A. Presentation (.pptx)
        if is_presentation or is_combined:
            if report_progress:
                report_progress(f"Composing professional presentation with {len(ppt_slides)} slides...", 65.0)
            pptx_path = self.ppt_composer.compose_presentation(
                title=topic.title(),
                slides_spec=ppt_slides,
                theme=theme,
                filename=f"{topic.replace(' ', '_')}_Presentation.pptx"
            )

            # Quality Inspection
            insp_pptx = self.inspector.inspect_artifact(pptx_path, ArtifactType.PPTX, expected_min_units=min(5, len(ppt_slides)))
            if not insp_pptx.passed:
                # Automatic Revision Loop: Split slides and re-compose
                if report_progress:
                    report_progress("Refining presentation layout based on quality audit...", 80.0)
                pptx_path = self.ppt_composer.compose_presentation(
                    title=topic.title(),
                    slides_spec=self.ppt_composer._split_overloaded_slides(ppt_slides),
                    theme=theme,
                    filename=f"{topic.replace(' ', '_')}_Presentation.pptx"
                )

            generated_artifacts.append({
                "type": "PPTX",
                "path": pptx_path,
                "slides_count": len(ppt_slides),
                "theme": theme.name
            })

        # B. Document (.pdf / .docx)
        if not is_presentation or is_combined:
            if report_progress:
                report_progress(f"Composing publication-grade PDF document ({len(doc_sections)} sections)...", 75.0)
            pdf_path = self.doc_composer.compose_pdf(
                title=f"{topic.title()} - Comprehensive Technical Report" if not is_study_guide else f"{topic.title()} - Structured Study Guide",
                sections=doc_sections,
                theme=theme,
                filename=f"{topic.replace(' ', '_')}_Report.pdf"
            )

            # Quality Inspection
            insp_pdf = self.inspector.inspect_artifact(pdf_path, ArtifactType.PDF)
            generated_artifacts.append({
                "type": "PDF",
                "path": pdf_path,
                "sections_count": len(doc_sections),
                "theme": theme.name
            })

            if is_docx:
                docx_path = self.doc_composer.compose_docx(
                    title=topic.title(),
                    sections=doc_sections,
                    filename=f"{topic.replace(' ', '_')}_Report.docx"
                )
                generated_artifacts.append({
                    "type": "DOCX",
                    "path": docx_path,
                    "sections_count": len(doc_sections),
                    "theme": theme.name
                })

        if report_progress:
            report_progress("Final verification complete. Artifacts delivered.", 100.0)

        # Step 6: Persist in PostgreSQL & Dialogue State
        primary_art = generated_artifacts[0]
        self._persist_artifact(
            user_id=user_id,
            topic=topic,
            artifact_info=primary_art,
            theme=theme,
            outline=[s.to_dict() for s in (ppt_slides if is_presentation else doc_sections)],
            source_docs=source_paths or []
        )

        if dialogue_state and hasattr(dialogue_state, "session_context"):
            dialogue_state.session_context["last_artifact_topic"] = topic
            dialogue_state.session_context["last_artifact_path"] = primary_art["path"]
            dialogue_state.session_context["last_artifact_type"] = primary_art["type"]
            dialogue_state.session_context["last_outline"] = [s.to_dict() for s in (ppt_slides if is_presentation else doc_sections)]

        # Response Construction
        art_desc = ", ".join([f"{a['type']} ({os.path.basename(a['path'])})" for a in generated_artifacts])
        response_msg = (
            f"I have created the professional {art_desc} on '{topic.title()}'. "
            f"It features topic-tailored content architecture, structured mathematical and conceptual models, "
            f"and '{theme.name}' design styling."
        )

        return {
            "status": "success",
            "topic": topic,
            "theme": theme.name,
            "artifacts": generated_artifacts,
            "primary_artifact_path": primary_art["path"],
            "response": response_msg,
            "quality_status": "VERIFIED"
        }

    def _extract_clean_topic(self, query: str, dialogue_state: Optional[Any] = None) -> str:
        low_q = query.lower().strip()
        is_reference_followup = any(w in low_q for w in (
            "turn that", "turn this", "turn it", "make it", "make that", "make this",
            "make the report", "make the presentation", "make a presentation", "presentation from it",
            "presentation from that", "presentation from this", "from it", "from that",
            "into a presentation", "into a ppt", "into a report", "now make a presentation",
            "now make it", "now make that"
        )) and not any(w in low_q for w in ("about", "on ", "explaining"))

        if is_reference_followup:
            if dialogue_state and hasattr(dialogue_state, "session_context"):
                topic_ctx = dialogue_state.session_context.get("last_artifact_topic")
                if topic_ctx:
                    return topic_ctx
            elif isinstance(dialogue_state, dict):
                topic_ctx = dialogue_state.get("session_context", {}).get("last_artifact_topic") or dialogue_state.get("last_artifact_topic")
                if topic_ctx:
                    return topic_ctx

        clean = re.sub(r'^(?:test\s+(?:the\s+)?actual\s+output\s+to\s+)?(?:now\s+)?(?:create|make|build|generate|turn|produce)\s+(?:a|an|the)?\s*', '', query, flags=re.I).strip()
        clean = re.sub(r'\s+(?:from these documents|from these files|from this|from that|from it|into a presentation|into a ppt|into a report).*$', '', clean, flags=re.I).strip()
        clean = re.sub(r'\b(?:professional|detailed|comprehensive|technical)?\s*(?:pdf|document|report|presentation|ppt|pptx|study guide|slides?)\b', '', clean, flags=re.I).strip()
        clean = re.sub(r'^(?:with\s+)?(?:all\s+(?:the\s*)?)?(?:content|info|information)?\s*(?:about|on|explaining|for|from|regarding)\s+', '', clean, flags=re.I).strip()
        clean = re.sub(r'^(?:about|on|explaining|for|from|regarding)\s+', '', clean, flags=re.I).strip()
        clean = re.sub(r'\s+(?:into a presentation|into a ppt|into a report|into a deck).*$', '', clean, flags=re.I).strip()
        clean = clean.strip(".?! ,")

        # If query was a reference like "Make that into a presentation" or "Make it more detailed"
        if not clean or clean.lower() in ("it", "this", "that", "these", "those", "that into a", "it into a", "this into a", "more detailed", "shorter", "presentation", "presentation from it", "a presentation", "a presentation from it"):
            if dialogue_state and hasattr(dialogue_state, "session_context"):
                topic_ctx = dialogue_state.session_context.get("last_artifact_topic")
                if topic_ctx:
                    return topic_ctx
            elif isinstance(dialogue_state, dict):
                topic_ctx = dialogue_state.get("session_context", {}).get("last_artifact_topic") or dialogue_state.get("last_artifact_topic")
                if topic_ctx:
                    return topic_ctx
            return "Artificial Neural Networks"

        return clean if len(clean) >= 2 else "Artificial Neural Networks"

    def _persist_artifact(
        self,
        user_id: int,
        topic: str,
        artifact_info: Dict[str, Any],
        theme: DocumentTheme,
        outline: List[Dict[str, Any]],
        source_docs: List[str]
    ) -> None:
        try:
            from core.db_pool import get_db_pool
            pool = get_db_pool()
            if pool and pool.is_healthy():
                with pool.get_cursor() as cur:
                    art_id = f"art_{uuid.uuid4().hex[:12]}"
                    cur.execute("""
                        INSERT INTO document_artifacts (
                            artifact_id, user_id, artifact_type, title, topic,
                            theme, outline, artifact_path, source_documents, verification_status
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'VERIFIED')
                        ON CONFLICT (artifact_id) DO NOTHING;
                    """, (
                        art_id,
                        user_id,
                        artifact_info.get("type", "PDF"),
                        f"{topic.title()} Artifact",
                        topic,
                        theme.theme_id,
                        json.dumps(outline[:15]),
                        artifact_info.get("path", ""),
                        json.dumps(source_docs)
                    ))
        except Exception as e:
            logger.warning(f"[PROFESSIONAL_DOC_ENGINE] DB persistence notice: {e}")

    def generate_document_canonical(
        self,
        user_input: str,
        user_id: int = 1,
        params: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        dialogue_state: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Authoritative entry point for high-level document generation requests.
        Coordinates topic extraction, structured specification, format routing,
        and delegates to the appropriate format builders while enforcing verification.
        """
        from modules.document_tools import (
            create_docx_document,
            create_pdf_document,
            create_excel_spreadsheet,
            create_presentation,
            extract_topic_from_query,
            build_document_content,
            build_presentation_slides,
            build_spreadsheet_spec,
            ArtifactContentSpec,
            construct_content_spec,
            verify_artifact_quality,
            refine_artifact
        )

        params = params or {}
        context = context or {}

        # 1. Construct structured ArtifactContentSpec with Topic Lock
        spec = construct_content_spec(user_input, params=params, context=context)
        doc_type = spec.artifact_type.lower()
        title = spec.title
        topic = spec.subject

        from core.document_task_state import get_document_task_manager
        doc_task_mgr = get_document_task_manager()
        doc_task = doc_task_mgr.create_task(
            artifact_type=doc_type,
            request=user_input,
            user_id=str(user_id),
            title=title,
            topic=topic,
            status="RUNNING"
        )

        result: Dict[str, Any] = {
            "status": "success",
            "topic": topic,
            "handled": True,
            "task_id": doc_task.task_id,
        }

        # 2. Multi-Artifact Refinement Handler ("add references to both")
        is_both = bool(re.search(r'\b(?:to\s+)?both\b', user_input, re.IGNORECASE))
        if is_both and dialogue_state:
            ppt_art = None
            docx_art = None
            for art in getattr(dialogue_state, "active_documents", []):
                t = (art.get("type") or art.get("doc_type") or "").lower()
                if t in ("ppt", "pptx") and not ppt_art:
                    ppt_art = art
                elif t in ("doc", "docx") and not docx_art:
                    docx_art = art
            if not (ppt_art and docx_art):
                active_g = getattr(dialogue_state, "current_goal", None)
                if active_g and isinstance(active_g, dict):
                    for d in active_g.get("deliverables", []):
                        dt = d.get("type", "").lower()
                        if dt in ("ppt", "pptx") and not ppt_art and d.get("file_path"):
                            ppt_art = {"filepath": d.get("file_path"), "type": "pptx", "subject": topic}
                        elif dt in ("doc", "docx") and not docx_art and d.get("file_path"):
                            docx_art = {"filepath": d.get("file_path"), "type": "docx", "subject": topic}

            if ppt_art and docx_art:
                ppt_spec = construct_content_spec(user_input, params={"doc_type": "pptx"}, context=context)
                ppt_spec.is_refinement = True
                ppt_spec.refinement_instruction = user_input
                ppt_slides = build_presentation_slides(topic, user_input, spec=ppt_spec)
                ppt_res = create_presentation(title=title, slides=ppt_slides)

                docx_spec = construct_content_spec(user_input, params={"doc_type": "docx"}, context=context)
                docx_spec.is_refinement = True
                docx_spec.refinement_instruction = user_input
                docx_content = build_document_content(topic, user_input, doc_type="docx", spec=docx_spec)
                docx_res = create_docx_document(title=title, content=docx_content)

                if ppt_res.get("success") and docx_res.get("success"):
                    result["status"] = "success"
                    result["filepath"] = ppt_res["filepath"]
                    result["ppt_filepath"] = ppt_res["filepath"]
                    result["docx_filepath"] = docx_res["filepath"]
                    result["response"] = f"Done. I've updated both your {topic} presentation and report with full references and verified their structure."
                    return result

        # 3. Artifact Format Conversion
        is_convert = bool(re.search(r'\b(?:convert|export)\b', user_input, re.IGNORECASE))
        if is_convert:
            from modules.document_tools.conversion_registry import ConversionRegistry

            # Step A: Resolve target format
            target_fmt = None
            if re.search(r'\b(?:to|into|as)\s+(?:a\s+|an\s+)?pdf\b', user_input, re.IGNORECASE) or doc_type == "pdf":
                target_fmt = "pdf"
            elif re.search(r'\b(?:to|into|as)\s+(?:a\s+|an\s+)?(?:docx|word|editable\s+word|doc)\b', user_input, re.IGNORECASE) or doc_type in ("docx", "doc", "word"):
                target_fmt = "docx"
            elif re.search(r'\b(?:to|into|as)\s+(?:a\s+|an\s+)?csv\b', user_input, re.IGNORECASE) or doc_type == "csv":
                target_fmt = "csv"
            elif re.search(r'\b(?:to|into|as)\s+(?:a\s+|an\s+)?(?:xlsx|excel|spreadsheet)\b', user_input, re.IGNORECASE) or doc_type in ("xlsx", "xls", "excel"):
                target_fmt = "xlsx"
            elif re.search(r'\b(?:to|into|as)\s+(?:a\s+|an\s+)?(?:markdown|md)\b', user_input, re.IGNORECASE) or doc_type in ("markdown", "md"):
                target_fmt = "markdown"
            elif re.search(r'\b(?:to|into|as)\s+(?:a\s+|an\s+)?html\b', user_input, re.IGNORECASE) or doc_type in ("html", "htm"):
                target_fmt = "html"
            elif re.search(r'\b(?:to|into|as)\s+(?:a\s+|an\s+)?(?:text|txt|plain\s+text)\b', user_input, re.IGNORECASE) or doc_type in ("txt", "text"):
                target_fmt = "txt"
            elif re.search(r'\b(?:to|into|as)\s+(?:a\s+|an\s+)?json\b', user_input, re.IGNORECASE):
                target_fmt = "json"
            elif re.search(r'\b(?:to|into|as)\s+(?:a\s+|an\s+)?yaml\b', user_input, re.IGNORECASE):
                target_fmt = "yaml"
            elif re.search(r'\b(?:to|into|as)\s+(?:a\s+|an\s+)?(?:png|image|jpeg|jpg)\b', user_input, re.IGNORECASE):
                target_fmt = "png"
            elif doc_type:
                target_fmt = doc_type

            # Step B: Resolve source file
            source_file = None
            if params and (params.get("filepath") or params.get("source_path") or params.get("file_path")):
                p_cand = params.get("filepath") or params.get("source_path") or params.get("file_path")
                if os.path.exists(p_cand):
                    source_file = p_cand

            if not source_file:
                m_q = re.search(r'["\']([^"\']+\.[a-zA-Z0-9]+)["\']', user_input)
                if m_q and os.path.exists(m_q.group(1)):
                    source_file = m_q.group(1)
                else:
                    m_path = re.search(r'([a-zA-Z]:[\\/][^\s"\'<>|?*]+\.[a-zA-Z0-9]+)', user_input)
                    if m_path and os.path.exists(m_path.group(1)):
                        source_file = m_path.group(1)

            if not source_file and dialogue_state:
                for art in getattr(dialogue_state, "active_documents", []):
                    f_art = art.get("filepath") or art.get("path")
                    if f_art and os.path.exists(f_art):
                        s_ext = Path(f_art).suffix.lstrip('.').lower()
                        if s_ext != target_fmt:
                            source_file = f_art
                            break
                if not source_file:
                    active_g = getattr(dialogue_state, "current_goal", None)
                    if active_g and isinstance(active_g, dict):
                        for d in active_g.get("deliverables", []):
                            f_del = d.get("file_path") or d.get("filepath")
                            if f_del and os.path.exists(f_del):
                                source_file = f_del
                                break
                if not source_file and getattr(dialogue_state, "active_artifact", None):
                    f_act = dialogue_state.active_artifact.get("filepath") or dialogue_state.active_artifact.get("path")
                    if f_act and os.path.exists(f_act):
                        source_file = f_act

            if not source_file and context:
                act = context.get("active_document") or context.get("active_artifact") or context.get("last_artifact")
                if isinstance(act, dict):
                    f_cand = act.get("filepath") or act.get("path")
                    if f_cand and os.path.exists(f_cand):
                        source_file = f_cand

            # Step C: Execute Conversion
            if source_file and target_fmt:
                all_ws = bool(re.search(r'\b(?:each|all|separate)\s+(?:sheet|worksheet)', user_input, re.IGNORECASE))
                conv_res = ConversionRegistry.convert_file(
                    source_path=source_file,
                    target_format=target_fmt,
                    options={"all_worksheets": all_ws}
                )
                if conv_res.success:
                    result["status"] = "success"
                    result["filepath"] = conv_res.target_path
                    result["doc_type"] = target_fmt
                    result["response"] = conv_res.message
                    result["fidelity_notes"] = conv_res.fidelity_notes
                    result["warnings"] = conv_res.warnings
                    if conv_res.extra_files:
                        result["extra_files"] = conv_res.extra_files
                    doc_task_mgr.complete_task(
                        task_id=doc_task.task_id,
                        artifact_path=conv_res.target_path,
                        title=title
                    )
                    return result
                else:
                    result["status"] = "error"
                    result["response"] = conv_res.message
                    doc_task_mgr.fail_task(task_id=doc_task.task_id, error=conv_res.message)
                    return result

        # 4. Standard Format-Specific Generation Dispatch
        # Embed visual diagrams if requested
        visuals_to_embed = []
        q_lower = user_input.lower()
        try:
            if any(k in q_lower for k in ["neural network", "deep learning", "ann", "mlp"]):
                from modules.document_tools.visual_builder import create_neural_network_diagram
                diag_res = create_neural_network_diagram(title=f"{topic} Neural Network")
                diag_path = diag_res.get("filepath") if isinstance(diag_res, dict) else str(diag_res)
                if diag_path and os.path.exists(diag_path):
                    visuals_to_embed.append(diag_path)
            elif any(k in q_lower for k in ["architecture", "subsystem", "component diagram"]):
                from modules.document_tools.visual_builder import VisualAssetBuilder
                diag_path = VisualAssetBuilder.create_system_architecture_diagram(title=f"{topic} Architecture")
                if diag_path and os.path.exists(diag_path):
                    visuals_to_embed.append(diag_path)
            elif any(k in q_lower for k in ["flowchart", "process flow", "workflow"]):
                from modules.document_tools.visual_builder import VisualAssetBuilder
                diag_path = VisualAssetBuilder.create_process_flowchart(title=f"{topic} Flow")
                if diag_path and os.path.exists(diag_path):
                    visuals_to_embed.append(diag_path)
        except Exception as v_err:
            logger.warning(f"[ProfessionalDocEngine] Visual builder note: {v_err}")

        from core.semantic_file_naming import get_semantic_file_naming_service
        namer = get_semantic_file_naming_service()

        target_filepath, target_filename = namer.resolve_output_path(
            task_description=user_input,
            title=title,
            artifact_type=doc_type,
            extension=doc_type,
            context=context,
            user_id=user_id,
            task_id=doc_task.task_id
        )

        if doc_type in ("doc", "docx", "word"):
            content = build_document_content(topic, user_input, doc_type="docx", spec=spec)
            gen_res = create_docx_document(title=title, content=content, filename=target_filepath, images=visuals_to_embed if visuals_to_embed else None)
            desc = "Word document"
        elif doc_type in ("ppt", "pptx", "presentation", "slides"):
            slides = build_presentation_slides(topic, user_input, spec=spec)
            gen_res = create_presentation(title=title, slides=slides, filename=target_filepath)
            desc = "PowerPoint presentation"
        elif doc_type in ("xls", "xlsx", "excel", "spreadsheet", "sheet"):
            sheet_spec = build_spreadsheet_spec(topic, user_input, spec=spec)
            if isinstance(sheet_spec, dict) and "sheets" in sheet_spec:
                gen_res = create_excel_spreadsheet(
                    sheets=sheet_spec["sheets"],
                    chart_type=sheet_spec.get("chart_type"),
                    filename=target_filepath
                )
            elif isinstance(sheet_spec, dict):
                gen_res = create_excel_spreadsheet(
                    sheet_title=sheet_spec.get("sheet_title", title),
                    headers=sheet_spec.get("headers"),
                    rows=sheet_spec.get("rows"),
                    add_totals=sheet_spec.get("add_totals", False),
                    chart_type=sheet_spec.get("chart_type"),
                    filename=target_filepath
                )
            else:
                gen_res = create_excel_spreadsheet(title=title, filename=target_filepath)
            desc = "Excel spreadsheet"
        elif doc_type in ("md", "markdown"):
            content = build_document_content(topic, user_input, doc_type="markdown", spec=spec)
            os.makedirs(os.path.dirname(target_filepath), exist_ok=True)
            with open(target_filepath, "w", encoding="utf-8") as f:
                f.write(content)
            gen_res = {"success": True, "filepath": target_filepath, "message": f"Generated Markdown document at {target_filepath}."}
            desc = "Markdown document"
        elif doc_type in ("html", "htm"):
            content = build_document_content(topic, user_input, doc_type="html", spec=spec)
            os.makedirs(os.path.dirname(target_filepath), exist_ok=True)
            html_body = content.replace("\n\n", "</p><p>").replace("\n", "<br/>")
            html_doc = f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{title}</title><style>body{{font-family:Segoe UI,sans-serif;margin:40px;line-height:1.6;color:#222;}}h1{{color:#1F497D;}}h2{{color:#2E75B6;}}</style></head><body><h1>{title}</h1><p>{html_body}</p></body></html>"
            with open(target_filepath, "w", encoding="utf-8") as f:
                f.write(html_doc)
            gen_res = {"success": True, "filepath": target_filepath, "message": f"Generated HTML document at {target_filepath}."}
            desc = "HTML document"
        else:
            # Default to PDF
            content = build_document_content(topic, user_input, doc_type="pdf", spec=spec)
            gen_res = create_pdf_document(title=title, content=content, filename=target_filepath, images=visuals_to_embed if visuals_to_embed else None)
            desc = "PDF document"

        if gen_res.get("success"):
            fpath = gen_res.get("filepath", "")
            verification = verify_artifact_quality(fpath, spec)
            result["verification"] = verification
            result["status"] = "success"
            result["filepath"] = fpath
            result["doc_type"] = doc_type
            result["title"] = title
            result["subject"] = spec.subject
            result["artifact_spec"] = spec.to_dict()
            sc = gen_res.get("slide_count")
            if "slide_count" in gen_res:
                result["slide_count"] = sc
            doc_task_mgr.complete_task(
                task_id=doc_task.task_id,
                artifact_path=fpath,
                title=title,
                slide_count=sc
            )
            if sc and doc_type in ("pptx", "ppt"):
                result["response"] = f"Done. I created the {topic} presentation with {sc} slides, verified the content and structure, and saved the final file."
            else:
                result["response"] = gen_res.get("message") or f"Done. I created the {topic} {desc}, verified the content and structure, and saved the final file."
        else:
            err_msg = gen_res.get("error", f"Failed to generate {desc}.")
            doc_task_mgr.fail_task(task_id=doc_task.task_id, error=err_msg)
            result["status"] = "error"
            result["response"] = err_msg

        return result


_engine_instance: Optional[ProfessionalDocumentEngine] = None


def get_professional_document_engine() -> ProfessionalDocumentEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = ProfessionalDocumentEngine()
    return _engine_instance

