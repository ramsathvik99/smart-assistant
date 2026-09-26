"""
Content and Structure Generation Helper for Document Tools.
Generates substantive, professional content for DOCX, PPTX, XLSX, and PDF documents
based on user intent and natural language queries.
"""

import re
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple


def extract_topic_from_query(query: str, default: str = "General Overview") -> str:
    """Extract substantive topic from user query."""
    clean = re.sub(
        r'^(?:hey\s+|ok\s+|okay\s+)?(?:friday|nova|trevon|jarvis|assistant|computer)[,\s:]*',
        '',
        query,
        flags=re.IGNORECASE
    ).strip()
    clean = re.sub(
        r'\b(?:can\s+you\s+|please\s+)?(?:create|created|generate|generated|make|made|write|wrote|build|built)\s+(?:an?\s+)?'
        r'(?:word\s+doc(?:ument)?|docx|pdf(?:\s+document|\s+report)?|excel(?:\s+sheet|\s+spreadsheet|\s+file)?|spreadsheet|xlsx|powerpoint(?:\s+presentation)?|presentation|pptx|ppt|slides|document|report)\b',
        '',
        clean,
        flags=re.IGNORECASE
    ).strip()

    # Strip prefixes like "about", "on", "titled", "named", "for"
    clean = re.sub(r'^(?:with\s+\d+\s+slides?\s+)?(?:about|on|for|titled|named)\s+', '', clean, flags=re.IGNORECASE).strip()
    clean = re.sub(r'\b(?:with\s+\d+\s+slides?)\b', '', clean, flags=re.IGNORECASE).strip(' .?!')

    if not clean or len(clean) < 2:
        return default
    return clean.title()


def build_document_content(topic: str, query: str = "", doc_type: str = "docx") -> str:
    """Build substantive structured markdown content for Word or PDF documents."""
    topic_clean = topic.strip().title()
    top_lower = topic_clean.lower()

    if "ai" in top_lower or "artificial intelligence" in top_lower:
        return (
            f"# {topic_clean}: Foundations, Architectures, and Industry Applications\n\n"
            "## Executive Summary\n"
            "Artificial Intelligence represents the frontier of modern computational innovation. "
            "From automated decision systems to advanced foundation models, modern AI platforms "
            "synthesize vast data volumes to provide actionable insights, automate mission-critical workflows, "
            "and transform human-computer interaction across industries.\n\n"
            "## Core Methodologies & Technologies\n"
            "- **Supervised & Unsupervised Learning**: Established mathematical frameworks for predictive modeling and pattern recognition.\n"
            "- **Deep Neural Networks**: Hierarchical representational learning including convolutional, recurrent, and transformer layers.\n"
            "- **Large Language Models & Generative AI**: High-parameter multimodal systems capable of zero-shot reasoning and synthesis.\n"
            "- **Reinforcement Learning from Human Feedback (RLHF)**: Alignment techniques maximizing model utility, safety, and helpfulness.\n\n"
            "## Practical Deployment Domains\n"
            "- **Healthcare Diagnostics**: Early anomaly identification in radiological imaging and personalized drug discovery.\n"
            "- **Financial Intelligence**: Real-time fraud detection, automated portfolio optimization, and market prediction.\n"
            "- **Autonomous Systems**: Sensor fusion, computer vision, and real-time path planning in robotics.\n"
            "- **Enterprise Workflow Automation**: Intelligent agents, continuous knowledge retrieval, and synthetic document synthesis.\n\n"
            "## Responsible AI & Governance\n"
            "Deploying production-grade AI mandates rigorous validation protocols. Organizations must ensure transparent provenance, "
            "interpretability of high-stakes classifications, and strict adherence to user privacy and data security standards.\n"
        )
    elif "deep learning" in top_lower:
        return (
            f"# {topic_clean}: Architectures, Optimization, and Scalability\n\n"
            "## Overview\n"
            "Deep Learning utilizes stacked artificial neural networks to extract progressive levels of hierarchical features from raw data.\n\n"
            "## Key Network Paradigms\n"
            "- **Convolutional Networks (CNNs)**: Optimized for spatial invariance and image feature hierarchies.\n"
            "- **Transformer Architectures**: Self-attention mechanisms dominating modern sequence modeling.\n"
            "- **Residual Connections (ResNets)**: Mitigating vanishing gradients in very deep backpropagation graphs.\n"
            "- **Diffusion Models**: State-of-the-art continuous-time generative modeling for perceptual data.\n\n"
            "## Optimization Strategies\n"
            "- Adaptive gradient methods (AdamW, Lion) with cosine decay schedules.\n"
            "- Mixed-precision training (FP16/BF16) and distributed data parallelism.\n"
            "- Regularization techniques including stochastic dropout, LayerNorm, and weight decay.\n"
        )
    elif "machine learning" in top_lower:
        return (
            f"# {topic_clean}: Engineering Principles and Practical Pipelines\n\n"
            "## Introduction\n"
            "Machine Learning provides computational systems with the capability to infer patterns and optimize decisions from empirical observations without explicit rule programming.\n\n"
            "## End-to-End Pipeline\n"
            "- **Data Ingestion & Hygiene**: Automated imputation, scaling, and categorical encoding.\n"
            "- **Feature Engineering**: Dimensionality reduction via PCA and domain-specific feature synthesis.\n"
            "- **Model Selection & Hyperparameter Tuning**: Cross-validation, Bayesian optimization, and ensemble blending.\n"
            "- **Deployment & Monitoring**: Continuous inference tracking, data drift mitigation, and concept drift detection.\n\n"
            "## Evaluation Metrics\n"
            "- Classification: ROC-AUC, Precision-Recall curves, F1-score.\n"
            "- Regression: RMSE, MAE, R-squared variance explanation.\n"
        )
    else:
        return (
            f"# {topic_clean}: Analysis and Technical Overview\n\n"
            "## Introduction\n"
            f"This document provides a comprehensive technical overview and structured analysis of {topic_clean}.\n\n"
            "## Key Findings and Core Principles\n"
            f"- Structured assessment of operational requirements and baseline parameters for {topic_clean}.\n"
            "- Cross-functional implementation strategies emphasizing performance, reliability, and modularity.\n"
            "- Risk mitigation frameworks and continuous verification protocols.\n\n"
            "## Implementation Roadmap\n"
            "1. Phase 1: Requirement gathering and baseline benchmarking.\n"
            "2. Phase 2: Architecture design and prototype validation.\n"
            "3. Phase 3: Production deployment, telemetry observation, and user feedback integration.\n\n"
            "## Conclusion\n"
            f"Ongoing evaluation confirms that disciplined adherence to standard protocols ensures optimal success in {topic_clean} initiatives.\n"
        )


def build_presentation_slides(topic: str, query: str = "", num_slides: Optional[int] = None) -> List[Dict[str, Any]]:
    """Build structured slide specifications for PowerPoint presentation."""
    topic_clean = topic.strip().title()
    top_lower = topic_clean.lower()

    # Determine slide count
    m_count = re.search(r'\b(\d+)\s+slides?\b', query, re.IGNORECASE)
    total_slides = int(m_count.group(1)) if m_count else (num_slides or 5)
    total_slides = max(3, min(10, total_slides))

    if "ai" in top_lower or "artificial intelligence" in top_lower:
        base_slides = [
            {
                "type": "content",
                "title": "Executive Summary & Objectives",
                "bullets": [
                    "Definition and evolution of contemporary Artificial Intelligence",
                    "Transition from heuristic expert systems to adaptive foundation models",
                    "Strategic importance for automation, optimization, and human augmentation",
                    "Key performance indicators and operational goals"
                ],
                "notes": "Introduce the strategic landscape of AI and set expectations for the discussion."
            },
            {
                "type": "content",
                "title": "Core Architectures & Technologies",
                "bullets": [
                    "Deep Neural Networks and Self-Attention Transformer mechanisms",
                    "Multimodal representations (text, code, vision, audio)",
                    "Supervised fine-tuning (SFT) and Reinforcement Learning alignment",
                    "Retrieval-Augmented Generation (RAG) for deterministic ground-truth grounding"
                ],
                "notes": "Highlight technical components driving current state-of-the-art results."
            },
            {
                "type": "content",
                "title": "Industry Applications & Impact",
                "bullets": [
                    "Healthcare: Early diagnostic imaging, targeted therapeutics, clinical notes summarization",
                    "Finance: Sub-millisecond algorithmic risk analysis, predictive modeling, fraud detection",
                    "Autonomous Robotics: Real-time sensor fusion, environmental mapping, robotic actuation",
                    "Software Engineering: Autonomous code synthesis, test generation, security auditing"
                ],
                "notes": "Discuss high-impact real-world domains delivering validated ROI."
            },
            {
                "type": "content",
                "title": "Safety, Governance & Ethical AI",
                "bullets": [
                    "Algorithmic fairness, bias audits, and demographic parity",
                    "Model explainability and high-stakes auditing traceability",
                    "Data privacy compliance (GDPR, HIPAA, SOC 2)",
                    "Robust guardrails against adversarial prompting and data leakage"
                ],
                "notes": "Emphasize regulatory compliance and reliable production governance."
            },
            {
                "type": "content",
                "title": "Future Outlook & Recommendations",
                "bullets": [
                    "Emergence of proactive multi-agent collaborative workflows",
                    "Edge AI and on-device quantization for low-latency inference",
                    "Next steps: Phased pilot deployment and continuous observational telemetry"
                ],
                "notes": "Conclude with concrete next steps and roadmap execution."
            }
        ]
    elif "deep learning" in top_lower or "machine learning" in top_lower:
        base_slides = [
            {
                "type": "content",
                "title": "Foundational Concepts",
                "bullets": [
                    f"Core mathematical formulations of {topic_clean}",
                    "Empirical risk minimization and gradient descent optimization",
                    "Trade-offs between model variance and bias",
                    "Hardware acceleration using tensor processing units and GPUs"
                ],
                "notes": "Establish theoretical fundamentals before examining architecture details."
            },
            {
                "type": "content",
                "title": "Network Topologies & Pipelines",
                "bullets": [
                    "Convolutional architectures for spatial pattern extraction",
                    "Attention layers for dynamic contextual weighting",
                    "End-to-end training pipelines and automated normalization",
                    "Loss function engineering and regularization strategies"
                ],
                "notes": "Detail the engineering pipeline from raw data to trained weights."
            },
            {
                "type": "content",
                "title": "Training & Optimization Best Practices",
                "bullets": [
                    "Learning rate warmup and cosine annealing schedules",
                    "Distributed data-parallel and pipeline-parallel scaling",
                    "Quantization-aware training (QAT) for edge efficiency",
                    "Continuous validation and automated early stopping"
                ],
                "notes": "Share practical guidelines for training stability and cost efficiency."
            },
            {
                "type": "content",
                "title": "Deployment & Observability",
                "bullets": [
                    "Model serving via low-latency runtime engines (ONNX, TensorRT)",
                    "Live monitoring for distribution shift and drift",
                    "A/B testing and canary deployment patterns",
                    "Fault recovery and fallback heuristics"
                ],
                "notes": "Discuss productionizing models into active enterprise operations."
            },
            {
                "type": "content",
                "title": "Conclusions & Next Steps",
                "bullets": [
                    "Summary of key findings and benchmark evaluations",
                    "Milestones for iterative architecture enhancements",
                    "Collaborative integration across cross-functional engineering teams"
                ],
                "notes": "Summarize key takeaways and outline implementation steps."
            }
        ]
    else:
        base_slides = [
            {
                "type": "content",
                "title": f"Introduction to {topic_clean}",
                "bullets": [
                    f"Background and contextual overview of {topic_clean}",
                    "Identification of primary challenges and opportunities",
                    "Scope, constraints, and operational targets",
                    "Strategic value proposition"
                ],
                "notes": f"Set the stage for {topic_clean}."
            },
            {
                "type": "content",
                "title": "Architecture & Methodology",
                "bullets": [
                    "Structured framework design and core modular components",
                    "Systematic data flow and interaction points",
                    "Standards compliance and security baseline",
                    "Operational efficiency benchmarks"
                ],
                "notes": "Explain how the system operates under standard conditions."
            },
            {
                "type": "content",
                "title": "Implementation & Verification",
                "bullets": [
                    "Progressive rollout phases with clear verification gates",
                    "Performance benchmarking and anomaly detection",
                    "Stakeholder alignment and user feedback loops",
                    "Reliability engineering and disaster recovery"
                ],
                "notes": "Review the rollout milestones and verification procedures."
            },
            {
                "type": "content",
                "title": "Summary & Strategic Roadmap",
                "bullets": [
                    "Key takeaways from the initial evaluation phase",
                    "Near-term priorities and resource allocation",
                    "Long-term vision and evolutionary roadmap"
                ],
                "notes": "Wrap up and answer questions from the audience."
            }
        ]

    # Adjust to requested slide count
    if total_slides < len(base_slides):
        return base_slides[:total_slides]
    elif total_slides > len(base_slides):
        # Add supplementary detail slides
        while len(base_slides) < total_slides:
            idx = len(base_slides) + 1
            base_slides.append({
                "type": "content",
                "title": f"Detailed Analysis (Part {idx})",
                "bullets": [
                    f"Granular evaluation metric {idx}.1 and baseline telemetry",
                    f"Optimization vector {idx}.2 for scalable performance",
                    f"Mitigation protocol {idx}.3 for identified edge cases",
                    f"Operational synthesis for milestone {idx}"
                ],
                "notes": f"Deep dive into specific operational aspect {idx}."
            })
    return base_slides


def build_spreadsheet_spec(query: str = "", title: str = "Data Summary") -> Dict[str, Any]:
    """
    Construct professional spreadsheet configuration with headers, rows,
    optional formulas, charts, and multiple sheets based on user query.
    """
    q_low = (query or "").lower()
    title_clean = (title or "Data Summary").strip().title()

    # Multi-sheet request
    is_multi_sheet = any(k in q_low for k in ["two sheets", "multiple sheets", "2 sheets", "second sheet", "both sheets"])
    add_totals = any(k in q_low for k in ["formula", "formulas", "total", "totals", "sum", "sums", "add formula", "add formulas"])
    chart_type = "bar" if any(k in q_low for k in ["chart", "graph", "plot", "bar chart"]) else ("line" if "line chart" in q_low else None)

    if is_multi_sheet:
        return {
            "sheets": [
                {
                    "title": "Revenue",
                    "headers": ["Quarter", "Product A", "Product B", "Product C", "Total Revenue"],
                    "rows": [
                        ["Q1 2026", 45000, 32000, 18500, 95500],
                        ["Q2 2026", 52000, 38500, 22000, 112500],
                        ["Q3 2026", 61000, 44000, 26500, 131500],
                        ["Q4 2026", 74000, 51000, 33000, 158000]
                    ],
                    "totals": add_totals
                },
                {
                    "title": "Expenses",
                    "headers": ["Category", "Q1 Budget", "Q1 Actual", "Variance"],
                    "rows": [
                        ["Engineering & R&D", 35000, 33500, 1500],
                        ["Infrastructure & Cloud", 18000, 19200, -1200],
                        ["Marketing & Growth", 14000, 13100, 900],
                        ["Operations & Admin", 8500, 8200, 300]
                    ],
                    "totals": add_totals
                }
            ],
            "chart_type": chart_type or "bar",
            "add_totals": add_totals
        }

    # Student roster / marks request
    if any(k in q_low for k in ["student", "marks", "grades", "scores", "class", "exam"]):
        headers = ["Student ID", "Full Name", "Subject", "Score", "Grade"]
        rows = [
            ["STU-101", "Aarav Sharma", "Computer Science", 94, "A"],
            ["STU-102", "Diya Patel", "Computer Science", 88, "B+"],
            ["STU-103", "Rohan Verma", "Computer Science", 96, "A+"],
            ["STU-104", "Ananya Reddy", "Computer Science", 79, "C+"],
            ["STU-105", "Kabir Mehta", "Computer Science", 91, "A-"],
            ["STU-106", "Sneha Nair", "Computer Science", 85, "B"]
        ]
        return {
            "sheet_title": "Student Marks" if "mark" in q_low else "Students",
            "headers": headers,
            "rows": rows,
            "add_totals": add_totals,
            "chart_type": chart_type
        }

    # Name and marks specific request
    if "name and mark" in q_low or "names and mark" in q_low:
        headers = ["Name", "Marks"]
        rows = [
            ["Aarav", 94],
            ["Diya", 88],
            ["Rohan", 96],
            ["Ananya", 79],
            ["Kabir", 91],
            ["Sneha", 85]
        ]
        return {
            "sheet_title": "Marks",
            "headers": headers,
            "rows": rows,
            "add_totals": add_totals,
            "chart_type": chart_type
        }

    # Default structured spreadsheet
    headers = ["Item ID", "Description", "Category", "Quantity", "Unit Price", "Total Value"]
    rows = [
        ["INV-001", "Enterprise Server Blade", "Hardware", 8, 2400, 19200],
        ["INV-002", "Layer 3 Gigabit Switch", "Networking", 14, 850, 11900],
        ["INV-003", "Precision Power Supply", "Components", 25, 180, 4500],
        ["INV-004", "Rackmount Cooling Module", "Facilities", 6, 620, 3720],
        ["INV-005", "Shielded Fiber Patch Cord", "Cabling", 60, 25, 1500]
    ]
    return {
        "sheet_title": title_clean if title_clean and title_clean != "Document" else "Data Summary",
        "headers": headers,
        "rows": rows,
        "add_totals": add_totals,
        "chart_type": chart_type
    }
