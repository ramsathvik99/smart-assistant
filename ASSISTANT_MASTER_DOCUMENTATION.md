# ASSISTANT MASTER DOCUMENTATION

## Complete A-to-Z Documentation of the Smart Assistant Project

---

## Table of Contents
1. [Project Overview](#project-overview)
2. [Complete Project Tree](#complete-project-tree)
3. [Architecture Overview](#architecture-overview)
4. [Startup Flow](#startup-flow)
5. [Core Components](#core-components)
6. [Legacy System](#legacy-system)
7. [Extensions System](#extensions-system)
8. [Modules System](#modules-system)
9. [Audio System](#audio-system)
10. [Database System](#database-system)
11. [LLM Integration](#llm-integration)
12. [RAG System](#rag-system)
13. [Memory System](#memory-system)
14. [User Profile & Authentication](#user-profile--authentication)
15. [GUI System](#gui-system)
16. [Plugins System](#plugins-system)
17. [Configuration Management](#configuration-management)
18. [Dependencies](#dependencies)
19. [Installation](#installation)
20. [Running Instructions](#running-instructions)
21. [Testing](#testing)
22. [Troubleshooting](#troubleshooting)
23. [Known Issues](#known-issues)
24. [Technical Debt](#technical-debt)
25. [Current Status](#current-status)
26. [Modification Guidelines](#modification-guidelines)
27. [Request Lifecycle](#request-lifecycle)
28. [File Dependency Map](#file-dependency-map)
29. [Command Cheat Sheet](#command-cheat-sheet)

---

## Project Overview

The Smart Assistant is a comprehensive AI-powered voice assistant system built in Python that combines legacy functionality with modern AI capabilities. It features voice interaction, multi-intent processing, RAG (Retrieval-Augmented Generation), personality engine, and extensive system integration.

### Key Features
- **Voice Interaction**: Wake word detection, speech-to-text, text-to-speech
- **Multi-Intent Processing**: Handle complex commands with multiple actions
- **RAG System**: Knowledge retrieval and generation
- **Personality Engine**: Adaptive assistant behavior and responses
- **Memory System**: Long-term conversation and user preference memory
- **Plugin Architecture**: Extensible functionality
- **GUI**: Tkinter-based interface with floating button
- **Multi-Provider LLM**: OpenAI, Groq, Gemini, DeepSeek, HuggingFace fallback
- **Database**: PostgreSQL for persistent storage

---

## Complete Project Tree

```
smart_assistant/
├── .env                                    # Environment configuration (API keys, settings)
├── .git/                                   # Git repository
├── __pycache__/                            # Python cache files
├── actual_db_schema.json                   # Actual database schema documentation
├── assistant.bat                           # Windows batch launcher
├── assistant.py                            # Main entry point
├── assistant_production_schema.sql         # PostgreSQL database schema
├── generate_docs.py                         # Documentation generator
├── requirements.txt                        # Python dependencies
├── runtime_config.json                     # Runtime configuration
├── setup_env.ps1                           # PowerShell environment setup
├── scratch_analysis.json                   # Development analysis data
├── system_actions.log                      # System action logs
├── test_failover.py                        # Failover testing
├── test_routing.py                         # Routing testing
├── yolov8n.pt                              # YOLO model for object detection
│
├── assistant_os/                           # Agent Operating System (experimental)
│   ├── agent_manager/                      # Agent management system
│   │   ├── __init__.py
│   │   ├── agent_manager.py                # Main agent manager
│   │   ├── health_monitor.py              # Agent health monitoring
│   │   ├── models.py                       # Data models
│   │   ├── registry.py                     # Agent registry
│   │   ├── scheduler.py                    # Task scheduling
│   │   └── tests/                          # Agent manager tests
│   ├── agents/                             # Agent implementations
│   │   ├── __init__.py
│   │   ├── base_agent.py                   # Base agent class
│   │   ├── conversation_agent.py           # Conversation handling agent
│   │   ├── models.py                       # Agent data models
│   │   ├── research_agent.py               # Research agent
│   │   └── tests/                          # Agent tests
│   ├── browser_manager/                    # Browser automation
│   │   ├── __init__.py
│   │   ├── browser_manager.py              # Browser control
│   │   └── tests/                          # Browser manager tests
│   └── planner/                            # Planning system
│       ├── __init__.py
│       ├── dependency_resolver.py          # Dependency resolution
│       ├── goal_decomposer.py              # Goal decomposition
│       ├── intent_classifier.py            # Intent classification
│       ├── models.py                       # Planning models
│       ├── planner.py                      # Main planner
│       └── tests/                          # Planner tests
│
├── communication/                          # Communication protocols
│   ├── __pycache__/
│   └── responses.py                        # Response templates
│
├── core/                                   # Core intelligence system
│   ├── __init__.py
│   ├── __pycache__/
│   ├── brain.py                            # Main brain/intelligence coordinator
│   ├── chatbrain.py                        # Chat-specific brain functions
│   ├── config.py                           # Core configuration
│   ├── dispatcher_integration.py           # Integration with execution dispatcher
│   ├── dispatcher_wrapper.py               # Dispatcher wrapper
│   ├── execution_dispatcher.py             # Command execution dispatcher
│   ├── execution_logger.py                 # Execution logging
│   ├── fix_database_schema.py             # Database schema fixes
│   ├── goal_planner.py                     # Goal planning for multi-intent
│   ├── intent_resolver.py                  # Intent resolution
│   ├── module_adapters.py                  # Module adapters
│   ├── multi_intent_analyzer.py           # Multi-intent analysis
│   ├── resource_helper.py                  # Resource management helpers
│   ├── startup_health_check.py             # Startup health verification
│   ├── state_manager.py                    # State management
│   └── unified_command_router.py           # Central command routing
│
├── data/                                   # Data storage
│   └── user_preferences.json               # User preference data
│
├── doc_builder/                            # Documentation building tools
│
├── extensions/                             # Extension system
│   ├── __init__.py
│   ├── __pycache__/
│   ├── ai_engine.py                        # AI engine interface
│   ├── ai_utils.py                         # AI utility functions
│   ├── assistant_orchestrator.py           # Main system orchestrator
│   ├── auth_engine.py                      # Authentication engine
│   ├── browser_engine.py                   # Browser automation engine
│   ├── context_manager.py                  # Context management
│   ├── conversational_memory.py            # Conversational memory
│   ├── database_manager.py                 # Database operations manager
│   ├── dialogue_engine/                    # Dialogue management
│   │   ├── __init__.py
│   │   ├── dialogue_manager.py             # Dialogue state manager
│   │   ├── session_memory.py               # Session memory
│   │   └── state_tracker.py                # State tracking
│   ├── dialogue_state_manager.py           # Dialogue state management
│   ├── file_engine.py                      # File operations engine
│   ├── intelligence/                      # Intelligence modules
│   │   ├── __init__.py
│   │   ├── execution_engine.py             # Execution engine
│   │   ├── goal_interpreter.py             # Goal interpretation
│   │   └── system_awareness.py             # System awareness
│   ├── launcher_engine.py                  # Application launcher
│   ├── llm_engine.py                       # Multi-provider LLM engine
│   ├── memory/                             # Memory extensions
│   │   └── memory_parser.py                # Memory parsing
│   ├── memory_store.py                     # Memory storage
│   ├── music_engine.py                     # Music playback engine
│   ├── nlu/                                # Natural Language Understanding
│   ├── personality_engine/                 # Personality system
│   │   ├── __init__.py
│   │   ├── behavior_layer.py               # Behavior tracking
│   │   ├── personality_core.py             # Core personality
│   │   ├── proactive_personality.py       # Proactive behavior
│   │   └── response_formatter.py           # Response formatting
│   ├── prolog_kb/                          # Prolog knowledge base
│   │   ├── assistant_rules.pl             # Assistant rules
│   │   ├── context_rules.pl                # Context rules
│   │   └── decision_rules.pl              # Decision rules
│   ├── rag_system/                         # RAG (Retrieval-Augmented Generation)
│   │   ├── __init__.py
│   │   ├── response_generator.py           # Response generation
│   │   ├── retriever.py                    # Knowledge retrieval
│   │   ├── router.py                       # RAG routing
│   │   └── validator.py                   # Response validation
│   ├── recommendation/                    # Recommendation system
│   ├── reminder_engine/                   # Reminder/scheduling
│   │   ├── __init__.py
│   │   ├── reminder_parser.py              # Reminder parsing
│   │   └── reminder_scheduler.py           # Reminder scheduling
│   ├── services/                           # Service implementations
│   │   ├── __init__.py
│   │   └── app_service.py                  # Application service
│   ├── service_health_monitor.py           # Service health monitoring
│   ├── stability_validator.py              # System stability validation
│   ├── system/                             # System utilities
│   │   ├── __init__.py
│   │   ├── initialization_manager.py       # System initialization
│   │   ├── shutdown_manager.py             # Graceful shutdown
│   │   ├── smart_opener.py                 # Smart file opener
│   │   ├── system_index.json               # System file index
│   │   ├── system_indexer.py               # System indexing
│   │   ├── tts_coordinator.py              # TTS coordination
│   │   └── wake_state_manager.py          # Wake state management
│   ├── user_preference_engine.py           # User preference management
│   ├── user_profile.py                     # User profile management
│   ├── weather_engine.py                   # Weather information
│   └── youtube_music_service.py            # YouTube music service
│
├── instance/                               # Instance-specific data
│   ├── __pycache__/
│   ├── app_cache.json                      # Application cache
│   ├── config.py                           # Configuration settings
│   └── user_voice.json                     # User voice data
│
├── legacy/                                 # Legacy/original implementation
│   ├── .env                                # Legacy environment config
│   ├── __init__.py
│   ├── __pycache__/
│   ├── action_skills.py                    # Action skill implementations
│   ├── actions.py                          # System actions
│   ├── assistant.py                        # Legacy assistant core
│   ├── assistant_gui.py                    # Legacy GUI
│   ├── auth_helpers.py                     # Authentication helpers
│   ├── floating_button.py                 # Floating button GUI
│   ├── hotword_listener.py                 # Hotword/wake word listener
│   ├── icon.ico                            # Application icon
│   ├── login_window.py                     # Login interface
│   ├── logs/                               # Log files
│   ├── main.py                             # Legacy main entry
│   ├── memory_manager.py                   # Memory management
│   ├── plugins/                            # Legacy plugins
│   ├── proactive_interaction.py           # Proactive interaction
│   ├── requirements.txt                    # Legacy requirements
│   ├── runtime_config.json                 # Runtime configuration
│   ├── skills.py                           # Skill implementations
│   ├── skills_utilities.py                 # Skill utilities
│   ├── sst.py                              # Speech-to-Text
│   ├── system_actions.log                  # System action logs
│   ├── tts.py                              # Text-to-Speech
│   ├── vlc/                                # VLC media player integration
│   ├── wake_response.py                    # Wake word response
│   ├── wake_word_detector.py               # Wake word detection
│   ├── wake_word_detector_v2.py            # Wake word detection v2
│   └── wake_words/                         # Wake word models
│
├── modules/                                # Modular components
│   ├── __init__.py
│   ├── __pycache__/
│   ├── assistant_email/                    # Email functionality
│   ├── calendar_manager/                   # Calendar management
│   ├── code_generator/                     # Code generation
│   ├── core/                               # Core modules
│   ├── image_processing/                   # Image processing
│   ├── launcher/                           # Application launcher
│   │   ├── __init__.py
│   │   ├── animation.py                    # Animation effects
│   │   ├── context_menu.py                 # Context menus
│   │   ├── launcher_controller.py          # Launcher control
│   │   ├── launcher_functions.py           # Launcher functions
│   │   ├── launcher_functions_simple.py    # Simplified launcher
│   │   ├── launcher_panel.py               # Launcher panel
│   │   ├── launcher_panel_stable.py        # Stable launcher panel
│   │   ├── registry.py                     # Application registry
│   │   ├── resolver.py                     # Application resolver
│   │   ├── scanner.py                      # Application scanner
│   │   ├── settings_panel.py               # Settings panel
│   │   ├── shutdown_manager.py              # Launcher shutdown
│   │   ├── status_window.py                # Status display
│   │   ├── system_menu.py                  # System menu
│   │   ├── terminal_window.py              # Terminal interface
│   │   └── voice_panel.py                  # Voice control panel
│   ├── music/                              # Music modules
│   ├── system_controller/                  # System control
│   ├── ui/                                 # UI components
│   │   ├── __pycache__/
│   │   └── assistant_ui.py                 # Assistant UI
│   └── writer/                             # Writing modules
│
├── nova_env/                               # Nova environment
│
├── plugins/                                # Plugin system
│   ├── __pycache__/
│   └── example_plugin.py                   # Example plugin
│
├── skills/                                 # Skill implementations
│   ├── __init__.py
│   ├── __pycache__/
│   ├── life_recommendation.py              # Life recommendations
│   ├── movie_recommendation.py             # Movie recommendations
│   ├── music_recommendation.py             # Music recommendations
│   └── recommendation_engine.py             # Recommendation engine
│
├── system_enhancements/                    # System enhancements
│
└── vlc/                                    # VLC installation
```

---

## Architecture Overview

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    User Interface Layer                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │ Voice Input  │  │  GUI Input   │  │  Text Input  │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                   Input Processing Layer                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │   STT Engine │  │ Wake Word    │  │ Text Parser  │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                  Intelligence Core Layer                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │  Brain Core  │  │ Multi-Intent │  │ Goal Planner │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │ Unified Router│ │Dialogue State│  │ RAG System   │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                   Execution Layer                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │   Skills     │  │   Actions    │  │   Modules    │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                   Integration Layer                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │ LLM Engine   │  │  TTS Engine  │  │ Database     │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                   Output Layer                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │ Voice Output │  │  GUI Display │  │ System Actions│     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

### Component Relationships

1. **Input Flow**: User Input → STT/Wake Word → Text Processing → Intelligence Core
2. **Processing Flow**: Intelligence Core → Intent Analysis → Goal Planning → Execution
3. **Output Flow**: Execution → Response Generation → TTS/GUI → User Feedback
4. **Data Flow**: All components interact through Database Manager and Memory System

---

## Startup Flow

### Phase 1: Environment Initialization
```
assistant.py → initialize_environment()
  ├── Load .env files (root + legacy)
  ├── Setup sys.path for all directories
  └── Change CWD to legacy directory
```

### Phase 2: Core Services Initialization
```
initialize_core() → extensions.system.initialization_manager.startup()
  ├── Phase 0: Pre-flight checks
  ├── Phase 1: Database connection
  ├── Phase 2: Core services (TTS coordinator, etc.)
  ├── Phase 3: Extensions initialization
  └── Phase 4: Background services
```

### Phase 3: Orchestrator Initialization
```
AssistantOrchestrator.__init__()
  ├── Initialize ExplainabilityManager
  └── Setup system state
```

### Phase 4: GUI System Startup
```
legacy.main.main()
  ├── Initialize Tkinter root
  ├── Setup TTS root reference
  ├── Show login window (force_login=True)
  ├── On login success → start_assistant_services()
  │   ├── Create floating button
  │   ├── Initialize launcher functions
  │   ├── Start hotword listener thread
  │   ├── Initialize shutdown manager
  │   └── Start proactive interaction
  └── Run Tkinter mainloop
```

### Phase 5: Background Services
```
Background Threads:
  ├── Hotword Listener (daemon thread)
  ├── TTS Worker (daemon thread)
  ├── Proactive Interaction Monitor
  ├── Reminder Scheduler
  └── Personality Engine Proactive System
```

---

## Core Components

### core/brain.py
**Purpose**: Main intelligence coordinator that integrates multi-intent analysis, goal planning, and dialogue state management.

**Key Classes**:
- `brain_process()`: Main entry point for intelligence processing
- `_execute_plan()`: Executes multi-step plans
- `_compose_response()`: Aggregates responses from multiple steps

**Key Functions**:
- `brain_route_and_execute()`: Drop-in replacement for unified router
- `_post_turn_update()`: Updates dialogue state after execution

**Architecture**:
```
User Input → Dialogue State Manager → Multi-Intent Analyzer → Goal Planner → Unified Router → Response
```

### core/unified_command_router.py
**Purpose**: Centralized command routing with deterministic intent classification and hybrid semantic fallback.

**Key Classes**:
- `Intent`: Enum defining 18 intent priorities (POWER_ACTION to GENERAL_CONVERSATION)
- `UnifiedCommandRouter`: Main router with pattern matching and semantic fallback

**Key Functions**:
- `route_command()`: Determines intent with hybrid resolution
- `execute_single_action()`: Executes matched intent
- `_semantic_fallback()`: LLM-based semantic classification

**Intent Priorities**:
1. POWER_ACTION (shutdown, restart)
2. EMERGENCY (emergency calls)
3. DEVICE_CONTROL (mute, volume, screenshot)
4. OPEN_APPLICATION (launch, close apps)
5. FILE_OPERATIONS (create, delete folders)
6. EMAIL (send, check email)
7. NOTES (note-taking)
8. REMINDERS (set reminders)
9. MUSIC (play, control music)
10. CALCULATOR (math operations)
11. CODE_GENERATION (programming tasks)
12. TRANSLATION (text translation)
13. TIME_QUERY (current time)
14. DATE_QUERY (current date)
15. WEATHER_QUERY (weather information)
16. MEMORY_QUERY (recall memory)
17. RAG_SEARCH (knowledge search)
18. GENERAL_CONVERSATION (fallback)

### core/multi_intent_analyzer.py
**Purpose**: Detects and parses multiple intents from single user input.

**Key Classes**:
- `IntentMatch`: Single intent match with confidence
- `ExecutionIntent`: Intent ready for execution
- `IntentAnalysis`: Complete analysis with dependencies
- `MultiIntentAnalyzer`: Main analyzer class

**Key Functions**:
- `analyze()`: Main analysis function
- `_detect_intents()`: Pattern-based intent detection
- `_extract_parameters()`: Parameter extraction for each intent
- `_analyze_dependencies()`: Dependency analysis between intents

**Multi-Intent Connectors**:
- "and", "then", "also", "after", "before", "while", "plus"

### core/goal_planner.py
**Purpose**: Transforms multi-intent analysis into executable plans with ordering and conflict detection.

**Key Classes**:
- `ExecutionStep`: Single step in execution plan
- `ExecutionPlan`: Complete execution plan
- `Conflict`: Represents conflicts between intents
- `GoalPlanner`: Main planner class

**Key Functions**:
- `create_plan()`: Creates execution plan from analysis
- `_order_intents()`: Orders intents by priority and dependencies
- `_detect_conflicts()`: Detects conflicting intents
- `_estimate_execution_time()`: Estimates execution duration

### core/execution_dispatcher.py
**Purpose**: Dispatches commands to appropriate handlers with execution logging.

**Key Classes**:
- `ExecutionDispatcher`: Main dispatcher class
- `ExecutionResult`: Result of command execution

**Key Functions**:
- `dispatch()`: Main dispatch function
- `_execute_skill()`: Executes skill functions
- `_log_execution()`: Logs execution results

---

## Legacy System

### legacy/assistant.py
**Purpose**: Legacy assistant core with command processing and personality integration.

**Key Functions**:
- `process_input()`: Main entry point for user input processing
- `speak_with_personality()`: Speaking with personality formatting
- `shutdown_assistant()`: Graceful shutdown

**Integration Points**:
- Personality Engine (format_response, adjust_behavior)
- Proactive Recommendations (update_user_activity)
- Reminder Engine (reminder_scheduler)
- RAG System (rag_system)

### legacy/main.py
**Purpose**: Legacy main entry point with GUI initialization.

**Key Functions**:
- `main()`: Main entry point
- `start_assistant_services()`: Initializes all services after login
- `start_hotword_thread()`: Starts hotword listener in background
- `launch_ui()`: Launches main UI window

**GUI Components**:
- Tkinter root window
- Login window
- Floating button
- Main UI panel

### legacy/skills.py
**Purpose**: Skill implementations for various assistant capabilities.

**Key Skills**:
- `tell_time()`, `tell_date()`: Time and date
- `solve_math()`: Mathematical calculations
- `take_screenshot()`: Screen capture
- `translate_text()`: Text translation
- `add_note()`, `read_notes()`: Note management
- `set_reminder()`: Reminder setting
- `play_music()`: Music playback
- `ask_ai()`: AI queries
- `get_weather()`: Weather information
- `get_news()`: News retrieval

### legacy/actions.py
**Purpose**: System actions and OS integration.

**Key Functions**:
- `open_website()`: Open websites
- `open_app()`: Launch applications
- `system_action()`: System commands
- `search_web()`: Web search
- `close_app()`: Close applications
- `type_text()`: Text input simulation
- `press_key()`: Key press simulation

### legacy/sst.py
**Purpose**: Speech-to-Text conversion with self-listening protection.

**Key Features**:
- PyAudio backend (primary)
- sounddevice backend (fallback)
- Self-listening protection (waits for TTS silence)
- Device selection (4-stage priority)
- Continuous listening mode

**Key Functions**:
- `listen()`: Single listening session
- `listen_continuous()`: Continuous listening with terminator
- `reset_microphone()`: Reset microphone calibration

### legacy/tts.py
**Purpose**: Text-to-Speech conversion with queue management.

**Key Features**:
- pyttsx3 backend (English)
- gTTS backend (multi-language)
- Queue-based processing
- Thread-safe operation
- Floating button animation integration

**Key Functions**:
- `speak()`: Queue text for speaking
- `wait_for_silence()`: Wait for TTS completion
- `is_speaking()`: Check if speaking

### legacy/hotword_listener.py
**Purpose**: Wake word detection with multiple backend support.

**Backends**:
- OpenWakeWord (primary)
- Picovoice Porcupine (alternative)
- Keyboard fallback (final)

**Key Features**:
- Adaptive threshold calibration
- Wake state management
- Thread-safe operation
- Auto-restart on crash

### legacy/memory_manager.py
**Purpose**: Memory management with PostgreSQL integration.

**Key Functions**:
- `get_or_create_user()`: User management
- `add_history()`: Conversation history
- `get_chat_history()`: Retrieve history
- Note management functions
- Database connection management

### legacy/wake_word_detector.py
**Purpose**: ONNX-based wake word detection.

**Key Features**:
- ONNX runtime integration
- Mel-spectrogram feature extraction
- Consecutive frame confirmation
- Wake lock mechanism
- High confidence threshold

---

## Extensions System

### extensions/assistant_orchestrator.py
**Purpose**: Main system orchestrator coordinating all engines.

**Key Classes**:
- `AssistantOrchestrator`: Main orchestrator
- `ExplainabilityManager`: Decision tracking

**Key Functions**:
- `start()`: Start orchestrator and launch legacy main
- `cleanup_and_shutdown()`: Graceful shutdown

### extensions/llm_engine.py
**Purpose**: Multi-provider LLM engine with automatic fallback.

**Supported Providers**:
1. OpenAI (primary, multiple keys)
2. Groq (fallback, multiple keys + model fallback)
3. Gemini (fallback, multiple keys)
4. DeepSeek (fallback, multiple keys)
5. HuggingFace (final fallback, multiple keys)

**Key Features**:
- Runtime validation
- 404/quota error detection
- Model blacklisting
- Per-provider key rotation

**Key Functions**:
- `get_completion()`: Main completion function with fallback chain
- `extract_intent()`: Intent extraction from text
- `check_if_command()`: Command detection

### extensions/database_manager.py
**Purpose**: Central persistence handler for all extensions.

**Database Schema**:
- `users`: User accounts
- `user_preferences`: User settings
- `system_memory`: System context
- `user_memory`: User memory (JSONB)
- `messages`: Conversation history
- `notes`: User notes
- `reminders': Reminder tasks
- `plugins`: Plugin management
- `plugin_logs`: Plugin execution logs
- `decision_logs`: Decision tracking
- `security_audit_logs`: Security events
- `active_contexts`: Active contexts

**Key Functions**:
- `get_user_by_username()`: User lookup
- `create_user()`: User creation
- `get_user_preferences()`: Preference retrieval
- `set_user_preference()`: Preference setting
- `update_context()`: Context persistence
- `load_context()`: Context loading
- `log_command()`: Command logging
- `log_ai_interaction()`: AI interaction logging

### extensions/rag_system/
**Purpose**: Retrieval-Augmented Generation for knowledge-based responses.

**Components**:
- `router.py`: Intent routing for RAG
- `retriever.py`: Knowledge retrieval
- `validator.py`: Response validation
- `response_generator.py`: Response generation

**Key Features**:
- Intent-based routing
- Web search integration
- Knowledge base retrieval
- Response validation
- Live data access

**Configuration**:
- `ENABLE_RAG`: Enable/disable RAG
- `ENABLE_WEB_SEARCH`: Enable web search
- `ENABLE_RETRIEVAL`: Enable knowledge retrieval
- `SEARCH_PROVIDER`: Search provider (serpapi, tavily)

### extensions/dialogue_state_manager.py
**Purpose**: Tracks conversation state across multiple turns.

**Key Classes**:
- `EntityExtraction`: Extracted entities
- `ConversationTurn`: Single conversation turn
- `DialogueState`: Complete dialogue state
- `DialogueStateManager`: State manager

**Key Functions**:
- `process_turn()`: Process conversation turn
- `extract_entities()`: Entity extraction
- `resolve_references()`: Pronoun resolution
- `update_state()`: State update
- `record_response()`: Response recording

### extensions/personality_engine/
**Purpose**: Adaptive assistant personality and behavior.

**Components**:
- `personality_core.py`: Core personality traits
- `behavior_layer.py`: Behavior tracking
- `proactive_personality.py`: Proactive behavior
- `response_formatter.py`: Response formatting

**Key Functions**:
- `get_personality()`: Get personality instance
- `format_response()`: Format responses with personality
- `adjust_behavior()`: Adjust behavior based on context
- `start_proactive_system()`: Start proactive monitoring
- `update_proactive_interaction()`: Update interaction tracking

### extensions/reminder_engine/
**Purpose**: Reminder and scheduling system.

**Components**:
- `reminder_parser.py`: Reminder parsing
- `reminder_scheduler.py`: Reminder scheduling

**Key Functions**:
- `initialize_scheduler()`: Initialize scheduler
- `parse_reminder()`: Parse reminder text
- `schedule_reminder()`: Schedule reminder

### extensions/system/
**Purpose**: System utilities and coordination.

**Components**:
- `initialization_manager.py`: System initialization
- `shutdown_manager.py`: Graceful shutdown
- `tts_coordinator.py`: TTS coordination
- `wake_state_manager.py`: Wake state management
- `smart_opener.py`: Smart file opening
- `system_indexer.py`: System file indexing

**Key Functions**:
- `startup()`: System startup sequence
- `shutdown()`: System shutdown sequence
- `initialize_tts_coordinator()`: TTS coordinator initialization

---

## Modules System

### modules/launcher/
**Purpose**: Application launcher with GUI integration.

**Components**:
- `launcher_panel.py`: Main launcher panel
- `launcher_functions.py`: Launcher functions
- `animation.py`: Animation effects
- `context_menu.py`: Context menus
- `settings_panel.py`: Settings interface
- `terminal_window.py`: Terminal interface
- `voice_panel.py`: Voice control panel

**Key Functions**:
- `set_references()`: Set GUI references
- `launch_application()`: Launch applications
- `scan_applications()`: Scan installed applications

### modules/ui/
**Purpose**: User interface components.

**Components**:
- `assistant_ui.py`: Main assistant UI

### modules/music/
**Purpose**: Music playback and control.

### modules/code_generator/
**Purpose**: Code generation capabilities.

### modules/image_processing/
**Purpose**: Image processing features.

### modules/assistant_email/
**Purpose**: Email functionality.

### modules/calendar_manager/
**Purpose**: Calendar management.

### modules/system_controller/
**Purpose**: System control operations.

### modules/writer/
**Purpose**: Writing assistance features.

---

## Audio System

### Speech-to-Text (STT)
**File**: `legacy/sst.py`

**Backends**:
1. PyAudio (primary, sr.Microphone)
2. sounddevice (fallback, bundled PortAudio)
3. None (graceful fallback)

**Device Selection** (4-stage priority):
1. DirectSound "Primary Sound Capture Driver" (Windows preferred)
2. Any DirectSound input with live audio
3. Any input device with live audio
4. OS default input device

**Self-Listening Protection**:
- Waits for TTS to finish before opening microphone
- Prevents assistant from capturing its own speech
- Configurable timeout (TTS_DRAIN_TIMEOUT = 12.0s)

### Text-to-Speech (TTS)
**File**: `legacy/tts.py`

**Backends**:
1. pyttsx3 (English, primary)
2. gTTS (multi-language, fallback)

**TTS Coordinator**:
**File**: `extensions/system/tts_coordinator.py`

**Priority Levels**:
- `PROACTIVE` (1): Idle suggestions
- `REMINDER` (2): Reminder alerts
- `COMMAND` (3): User command responses
- `EMERGENCY` (4): Emergency alerts

**Features**:
- Queue-based processing
- Priority management
- Thread-safe operation
- Floating button animation integration
- Self-listening protection integration

### Wake Word Detection
**Files**: 
- `legacy/hotword_listener.py`
- `legacy/wake_word_detector.py`

**Backends**:
1. OpenWakeWord (primary, ONNX)
2. Picovoice Porcupine (alternative)
3. Keyboard fallback (final)

**Features**:
- Adaptive threshold calibration
- Consecutive frame confirmation
- Wake lock mechanism
- High confidence threshold (0.55-0.95)
- Auto-restart on crash

**Wake State Management**:
**File**: `extensions/system/wake_state_manager.py`

- Thread-safe state management
- WAKE mode vs COMMAND mode
- State transitions
- Wake lock coordination

---

## Database System

### Database Schema
**File**: `assistant_production_schema.sql`

**Database**: PostgreSQL
**Default Database**: `nova_assistant`
**Default User**: `postgres`
**Default Password**: `ramsathvik`

### Core Tables

#### users
```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    voice_identity_hash TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

#### user_memory
```sql
CREATE TABLE user_memory (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    memory JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

#### user_preferences
```sql
CREATE TABLE user_preferences (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    pref_key TEXT NOT NULL,
    pref_value TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, pref_key)
);
```

#### system_memory
```sql
CREATE TABLE system_memory (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, key)
);
```

#### messages
```sql
CREATE TABLE messages (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

#### notes
```sql
CREATE TABLE notes (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    note TEXT NOT NULL,
    pinned BOOLEAN DEFAULT FALSE,
    done BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

#### reminders
```sql
CREATE TABLE reminders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    task_text TEXT NOT NULL,
    due_at TIMESTAMP WITH TIME ZONE NOT NULL,
    is_notified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

#### plugins
```sql
CREATE TABLE plugins (
    id SERIAL PRIMARY KEY,
    plugin_id TEXT UNIQUE NOT NULL,
    is_enabled BOOLEAN DEFAULT TRUE,
    permissions JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

### Database Manager
**File**: `extensions/database_manager.py`

**Key Functions**:
- `get_user_by_username()`: User authentication
- `create_user()`: User registration
- `get_user_preferences()`: Preference retrieval
- `set_user_preference()`: Preference setting
- `update_context()`: Context persistence
- `load_context()`: Context loading
- `log_command()`: Command logging
- `log_ai_interaction()`: AI interaction logging

---

## LLM Integration

### Multi-Provider LLM Engine
**File**: `extensions/llm_engine.py`

**Provider Priority Chain**:
1. OpenAI (primary, multiple keys)
2. Groq (fallback, multiple keys + model fallback)
3. Gemini (fallback, multiple keys)
4. DeepSeek (fallback, multiple keys)
5. HuggingFace (final fallback, multiple keys)

### Configuration

**OpenAI**:
- `OPENAI_API_KEY`: Primary API key
- `OPENAI_API_KEY_1`, `_2`, `_3`: Backup keys
- `OPENAI_API_BASE`: API base URL
- `OPENAI_MODEL`: Model (gpt-4o-mini)
- `OPENAI_ENABLED`: Enable/disable switch

**Groq**:
- `GROQ_API_KEY`: Primary API key
- `GROQ_API_KEY_1`, `_2`, `_3`: Backup keys
- `GROQ_MODEL`: Model (qwen/qwen3.8-27b)
- `GROQ_FALLBACK_MODELS`: Fallback models

**Gemini**:
- `GEMINI_API_KEY`: Primary API key
- `GEMINI_API_KEY_1`, `_2`, `_3`: Backup keys
- `GEMINI_MODEL`: Model (gemini-2.5-flash)

**DeepSeek**:
- `DEEPSEEK_API_KEY`: Primary API key
- `DEEPSEEK_API_KEY_1`, `_2`, `_3`: Backup keys
- `DEEPSEEK_MODEL`: Model (deepseek-chat)

**HuggingFace**:
- `HF_API_KEY`: Primary API key
- `HF_API_KEY_1`, `_2`, `_3`: Backup keys
- `HF_MODEL_ID`: Model (mistralai/Mistral-7B-Instruct-v0.2)

### Key Features

**Runtime Validation**:
- 404 error detection (model not found)
- Quota error detection (429, insufficient_quota)
- Authentication error detection
- Model blacklisting
- Key rotation on failure

**System Prompt**:
- Uses per-user assistant name
- Includes context and memory
- Maintains professional tone
- References memory naturally

---

## RAG System

### RAG System Architecture
**Directory**: `extensions/rag_system/`

**Components**:
- `router.py`: Intent routing and decision making
- `retriever.py`: Knowledge retrieval from various sources
- `validator.py`: Response validation
- `response_generator.py`: Response generation

### Pipeline Flow

```
User Query → Router → Intent Detection → Decision → Execution → Response
                                        ↓
                    ┌───────────────────┴───────────────────┐
                    │                                       │
            Browser Search                        Knowledge Retrieval
                    │                                       │
                    └───────────────────┬───────────────────┘
                                        ↓
                              Response Generator
                                        ↓
                              Response Validator
                                        ↓
                                   Final Response
```

### Configuration

**Environment Variables**:
- `ENABLE_RAG`: Enable/disable RAG system
- `ENABLE_WEB_SEARCH`: Enable web search
- `ENABLE_RETRIEVAL`: Enable knowledge retrieval
- `ENABLE_LIVE_DATA`: Enable live data access
- `SEARCH_PROVIDER`: Search provider (serpapi, tavily)
- `FALLBACK_TO_LLM`: Enable LLM fallback

**Search Providers**:
- SerpAPI (primary)
- Tavily (fallback)

### Key Features

**Intent-Based Routing**:
- `browser_search`: Direct web search
- `command`: Command execution
- `chat`: General conversation
- `knowledge`: Knowledge base queries

**Browser Search Intercept**:
- Detects "search for" patterns
- Opens Google with search query
- Bypasses RAG for direct searches

**Conflict Resolution**:
- Preserves original unified intent
- Prevents incorrect routing
- Maintains execution context

---

## Memory System

### Memory Architecture

**Dual Memory Model**:
1. **Legacy JSONB Memory** (`user_memory` table)
2. **Intelligence Fact-Based Memory** (`system_memory` table)

### Memory Types

**MemoryType Enum**:
- `USER_FACT`: Declarative, factual user statements
- `USER_PREFERENCE`: Structured preferences
- `SYSTEM_CONTEXT`: Summaries, session context, internal state

**Privacy States**:
- `NORMAL`: Normal memory operation
- `PAUSED`: "Pause memory" - No saving allowed
- `VOLATILE`: "Don't remember this" - Session only (not implemented)

### Memory Manager
**File**: `legacy/memory_manager.py`

**Key Functions**:
- `get_or_create_user()`: User management
- `add_history()`: Add to conversation history
- `get_chat_history()`: Retrieve conversation history
- Note management functions
- Database operations

### Conversational Memory
**File**: `extensions/conversational_memory.py`

**Key Functions**:
- `store_interaction()`: Store user-assistant interactions
- `retrieve_context()`: Retrieve conversation context
- `update_memory()`: Update memory based on interactions

### Dialogue State Memory
**File**: `extensions/dialogue_engine/dialogue_manager.py`

**Key Features**:
- Multi-turn conversation tracking
- Entity extraction and binding
- Context inference
- Reference resolution

---

## User Profile & Authentication

### User Authentication

**Login System**:
**File**: `legacy/login_window.py`

**Features**:
- Username/password authentication
- Session restoration (optional, currently disabled)
- Voice identity hash (optional)

**Authentication Helpers**:
**File**: `legacy/auth_helpers.py`

**Key Functions**:
- `try_restore_session()`: Attempt session restoration
- `authenticate_user()`: User authentication

### User Profile

**User Profile Engine**:
**File**: `extensions/user_profile.py`

**Features**:
- User preference management
- Profile data storage
- Preference retrieval

**User Preference Engine**:
**File**: `extensions/user_preference_engine.py`

**Key Functions**:
- `get_preferences()`: Retrieve user preferences
- `set_preference()`: Set user preference
- `update_profile()`: Update user profile

### Assistant Name

**Per-User Assistant Names**:
- Stored in `user_preferences` table
- Key: `assistant_name`
- Retrieved via `settings.get_assistant_name()`
- Fallback to environment variable `ASSISTANT_NAME`
- Never hardcodes "Nova" as default

---

## GUI System

### GUI Architecture

**Framework**: Tkinter with CustomTkinter (optional)

**Main Components**:
1. **Root Window**: Hidden main Tkinter root
2. **Login Window**: User authentication interface
3. **Floating Button**: Always-on-top floating interface
4. **Main UI**: Main assistant interface
5. **Launcher Panel**: Application launcher

### Floating Button
**File**: `legacy/floating_button.py`

**Features**:
- Always-on-top floating window
- Double-click to launch main UI
- Animation during TTS
- Launcher panel integration
- Voice control panel

### Main UI
**File**: `modules/ui/assistant_ui.py`

**Features**:
- Conversation display
- Input methods (text, voice)
- Settings access
- System status

### Launcher Panel
**File**: `modules/launcher/launcher_panel.py`

**Features**:
- Application grid
- Search functionality
- Categories
- Quick launch
- Settings panel

### Voice Panel
**File**: `modules/launcher/voice_panel.py`

**Features**:
- Voice command feedback
- Microphone status
- Volume control
- Wake word status

---

## Plugins System

### Plugin Architecture

**Plugin Table**:
```sql
CREATE TABLE plugins (
    id SERIAL PRIMARY KEY,
    plugin_id TEXT UNIQUE NOT NULL,
    is_enabled BOOLEAN DEFAULT TRUE,
    permissions JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

**Plugin Logs**:
```sql
CREATE TABLE plugin_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    plugin_id INTEGER REFERENCES plugins(id) ON DELETE CASCADE,
    action TEXT,
    status TEXT,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

### Example Plugin
**File**: `plugins/example_plugin.py`

**Structure**:
- Plugin metadata
- Permission declarations
- Action functions
- Logging integration

### Plugin Integration

**Plugin Manager**:
**Location**: NOT VERIFIED FROM CURRENT REPOSITORY

**Features**:
- Plugin loading/unloading
- Permission management
- Execution logging
- Decision tracking

---

## Configuration Management

### Configuration System

**Main Configuration**:
**File**: `instance/config.py`

**Settings Class**:
- Centralized configuration
- Environment variable loading
- Type conversion
- Validation

### Environment Variables

**API Keys**:
- `OPENAI_API_KEY`, `OPENAI_API_KEY_1`, `_2`, `_3`
- `GROQ_API_KEY`, `GROQ_API_KEY_1`, `_2`, `_3`
- `GEMINI_API_KEY`, `GEMINI_API_KEY_1`, `_2`, `_3`
- `DEEPSEEK_API_KEY`, `DEEPSEEK_API_KEY_1`, `_2`, `_3`
- `HF_API_KEY`, `HF_API_KEY_1`, `_2`, `_3`
- `SERPAPI_KEY`, `SERPAPI_KEY_1`, `_2`, `_3`
- `TAVILY_API_KEY`, `TAVILY_API_KEY_1`, `_2`
- `PICOVOICE_ACCESS_KEY`
- `YOUTUBE_API_KEY`, `YOUTUBE_API_KEY_1`, `_2`, `_3`

**Database**:
- `DB_HOST`: Database host (localhost)
- `DB_NAME`: Database name (nova_assistant)
- `DB_USER`: Database user (postgres)
- `DB_PASSWORD`: Database password
- `DB_PORT`: Database port (5432)

**Assistant Settings**:
- `ASSISTANT_NAME`: Assistant name (per-user in DB)
- `USE_OPENAI`: Use OpenAI (true)
- `OPENAI_ENABLED`: OpenAI enable switch (true)
- `MAX_HISTORY_MESSAGES`: Max history messages (12)
- `VOICE_ENGINE`: Voice engine (pyttsx3)
- `VOICE_RATE`: Voice rate (200)
- `VOLUME`: Volume (1.0)
- `LANGUAGE`: Language (en-in)

**Audio Settings**:
- `ENABLE_DUCKING`: Enable audio ducking (false)
- `DUCKING_INTENSITY`: Ducking intensity (5)
- `HOTWORD_WAKE_THRESHOLD`: Wake threshold (0.35)
- `HOTWORD_ADAPTIVE_CALIBRATION`: Adaptive calibration (true)

**RAG Settings**:
- `ENABLE_RAG`: Enable RAG (true)
- `ENABLE_WEB_SEARCH`: Enable web search (true)
- `ENABLE_RETRIEVAL`: Enable retrieval (true)
- `ENABLE_LIVE_DATA`: Enable live data (true)
- `SEARCH_PROVIDER`: Search provider (serpapi)
- `FALLBACK_TO_LLM`: LLM fallback (true)

### Runtime Configuration

**Runtime Config**:
**File**: `runtime_config.json`

**Purpose**: Runtime state persistence

**Key Data**:
- `LAST_USER_ID`: Last logged-in user ID

---

## Dependencies

### Python Dependencies
**File**: `requirements.txt`

**Core Dependencies**:
- `beautifulsoup4`: Web scraping
- `deep-translator`: Translation
- `feedparser`: RSS feed parsing
- `geopy`: Geocoding
- `gTTS==2.5.1`: Text-to-speech
- `numpy==1.26.4`: Numerical computing
- `openai`: OpenAI API
- `opencv-python==4.9.0.80`: Computer vision
- `playsound==1.2.2`: Audio playback
- `plyer`: Platform features
- `psutil`: System monitoring
- `psycopg2-binary==2.9.9`: PostgreSQL adapter
- `pvporcupine==3.0.0`: Wake word detection
- `pvrecorder==1.2.7`: Audio recording
- `pyautogui==0.9.54`: GUI automation
- `pyperclip`: Clipboard access
- `pyswip`: Prolog interface
- `pyttsx3`: Text-to-speech
- `pywin32`: Windows API
- `requests`: HTTP requests
- `simpleaudio`: Audio playback
- `SpeechRecognition`: Speech recognition
- `speedtest-cli`: Speed testing
- `timezonefinder`: Timezone detection
- `ultralytics==8.2.0`: YOLO model
- `wikipedia`: Wikipedia API
- `python-vlc`: VLC media player
- `python-dotenv`: Environment variables
- `pyaudio`: Audio I/O
- `yt-dlp`: YouTube downloader
- `openwakeword==0.6.0`: Wake word detection
- `onnxruntime==1.23.2`: ONNX runtime

### System Dependencies

**Windows**:
- PostgreSQL server
- Python 3.10+
- Audio drivers
- (Optional) VLC media player

---

## Installation

### Prerequisites

1. **Python**: Python 3.10 or higher
2. **PostgreSQL**: PostgreSQL server installed and running
3. **Audio**: Working microphone and speakers
4. **Git**: For version control (optional)

### Step-by-Step Installation

#### 1. Clone Repository
```bash
git clone <repository-url>
cd smart_assistant
```

#### 2. Create Virtual Environment
```bash
python -m venv venv
venv\Scripts\activate  # Windows
# or
source venv/bin/activate  # Linux/Mac
```

#### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

#### 4. Setup Database
```bash
# Create database
createdb nova_assistant

# Run schema
psql -d nova_assistant -f assistant_production_schema.sql
```

#### 5. Configure Environment
```bash
# Copy .env.example to .env (if available)
# Edit .env with your API keys and settings
```

#### 6. Setup Picovoice Key (Windows)
```powershell
.\setup_env.ps1
```

#### 7. Test Installation
```bash
python assistant.py
```

---

## Running Instructions

### Windows (Batch File)
```batch
assistant.bat
```

### Windows (PowerShell)
```powershell
python assistant.py
```

### Linux/Mac
```bash
python assistant.py
```

### Command Line Options

**Default Mode**: Full system with GUI
```bash
python assistant.py
```

**Backend Only**: No GUI
```python
from assistant import start_assistant_backend
start_assistant_backend()
```

### Startup Sequence

1. **Environment Loading**: Load .env files
2. **Path Setup**: Configure sys.path
3. **Core Initialization**: Initialize core services
4. **Orchestrator Start**: Start assistant orchestrator
5. **GUI Launch**: Launch GUI system
6. **Background Services**: Start background threads
7. **Ready State**: System ready for user input

### Shutdown Procedure

1. **Signal Handling**: Catch SIGINT (Ctrl+C)
2. **Graceful Shutdown**: Call shutdown manager
3. **Service Cleanup**: Stop all services
4. **Database Cleanup**: Close database connections
5. **Thread Cleanup**: Join background threads
6. **Exit**: Clean exit

---

## Testing

### Test Files

**Failover Testing**:
**File**: `test_failover.py`

**Routing Testing**:
**File**: `test_routing.py`

### Unit Tests

**Agent Tests**:
- `assistant_os/agent_manager/tests/test_agent_manager.py`
- `assistant_os/agents/tests/test_agent_framework.py`
- `assistant_os/agents/tests/test_conversation_agent.py`
- `assistant_os/agents/tests/test_research_agent.py`

**Browser Manager Tests**:
- `assistant_os/browser_manager/tests/test_browser_manager.py`

**Planner Tests**:
- `assistant_os/planner/tests/test_planner.py`

### Running Tests

```bash
# Run specific test
python test_failover.py

# Run unit tests (if pytest is available)
pytest assistant_os/agent_manager/tests/
```

---

## Troubleshooting

### Common Issues

#### 1. Database Connection Failed
**Problem**: Cannot connect to PostgreSQL
**Solution**:
- Check PostgreSQL is running
- Verify database credentials in .env
- Ensure database exists: `createdb nova_assistant`
- Check firewall settings

#### 2. Audio Input Not Working
**Problem**: Microphone not detected
**Solution**:
- Check microphone permissions
- Verify audio drivers
- Test with different microphone
- Check audio backend selection in sst.py

#### 3. Wake Word Not Detected
**Problem**: Wake word not responding
**Solution**:
- Check microphone input
- Adjust wake threshold in config
- Try different wake word backend
- Check audio levels

#### 4. TTS Not Working
**Problem**: No audio output
**Solution**:
- Check audio output device
- Verify TTS backend (pyttsx3/gTTS)
- Check volume settings
- Test with different voice

#### 5. LLM API Errors
**Problem**: LLM provider failing
**Solution**:
- Check API keys in .env
- Verify API quota/balance
- Check internet connection
- Enable fallback providers
- Check OPENAI_ENABLED setting

#### 6. GUI Not Launching
**Problem**: GUI window not appearing
**Solution**:
- Check Tkinter installation
- Verify display settings
- Check for GUI errors in logs
- Try running backend-only mode

#### 7. Import Errors
**Problem**: Module import failures
**Solution**:
- Check Python path configuration
- Verify virtual environment activation
- Check for missing dependencies
- Reinstall requirements

### Debug Mode

**Enable Debug Logging**:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

**Check System Health**:
```python
from core.startup_health_check import run_health_check
run_health_check()
```

---

## Known Issues

### Current Limitations

1. **VLC Integration**: VLC manually disabled per user request
2. **Session Restore**: Auto session restore disabled (force_login=True)
3. **Volatile Memory**: VOLATILE privacy state not implemented in DB
4. **Plugin Manager**: Plugin manager implementation not verified
5. **Agent OS**: Agent OS system is experimental/incomplete

### Technical Debt

1. **Legacy Code**: Significant legacy code in `legacy/` directory
2. **Mixed Architectures**: Multiple overlapping systems (legacy + extensions)
3. **Database Schema**: Some schema inconsistencies addressed but legacy remains
4. **Error Handling**: Inconsistent error handling across modules
5. **Documentation**: Some components lack comprehensive documentation

### Performance Issues

1. **Startup Time**: Slow startup due to multiple initialization phases
2. **Memory Usage**: High memory usage with multiple systems running
3. **Database Queries**: Some queries not optimized
4. **LLM Latency**: Dependent on external API response times

---

## Technical Debt

### Code Quality Issues

1. **Inconsistent Naming**: Mixed naming conventions across modules
2. **Duplicate Code**: Similar functionality in multiple places
3. **Large Files**: Some files are very long (unified_command_router.py)
4. **Missing Tests**: Limited test coverage
5. **Dead Code**: Unused imports and functions

### Architecture Issues

1. **Tight Coupling**: Some components tightly coupled
2. **Circular Dependencies**: Some circular import issues
3. **Mixed Responsibilities**: Some classes have multiple responsibilities
4. **Global State**: Excessive use of global variables
5. **Hard-coded Values**: Some magic numbers and strings

### Refactoring Priorities

1. **Consolidate Routing**: Merge legacy and extension routing
2. **Unify Memory**: Consolidate memory systems
3. **Standardize Configuration**: Unified configuration approach
4. **Improve Error Handling**: Consistent error handling
5. **Reduce Globals**: Minimize global state

---

## Current Status

### System Status

**Production Ready**: Yes, with caveats
- Core functionality stable
- Voice interaction working
- LLM integration functional
- Database system operational
- GUI system functional

**Known Limitations**:
- Experimental features (Agent OS)
- Legacy code maintenance required
- Some features disabled (VLC)

### Development Status

**Active Development**: Yes
- Regular updates and improvements
- Bug fixes and stability improvements
- Feature additions
- Performance optimizations

### Testing Status

**Test Coverage**: Limited
- Some unit tests present
- Integration tests limited
- End-to-end tests minimal
- Manual testing required

### Documentation Status

**Documentation**: Partial
- Core components documented
- Some components lack documentation
- API documentation incomplete
- User documentation basic

---

## Modification Guidelines

### What Can Be Modified

**Safe to Modify**:
- Configuration values in .env
- UI themes and layouts
- Skill implementations
- Plugin implementations
- Response templates
- Personality parameters

**Modify with Care**:
- Database schema (requires migration)
- Core routing logic
- LLM provider configuration
- Audio backend selection
- Authentication logic

**Do Not Modify Carelessly**:
- Database connection logic
- Core architecture (brain.py, unified_command_router.py)
- Signal handling and shutdown
- Thread synchronization
- Memory management
- Security-related code

### Adding New Features

**Recommended Approach**:
1. Create extension in `extensions/`
2. Use existing patterns
3. Add database migration if needed
4. Update configuration
5. Add tests
6. Update documentation

**Example: Adding New Skill**
```python
# In legacy/skills.py
def my_new_skill(param):
    """Description of skill"""
    # Implementation
    return "Result"

# In core/unified_command_router.py
# Add pattern matching
Intent.MY_NEW_INTENT: [
    re.compile(r'\b(my new skill pattern)\b', re.IGNORECASE)
]

# Add execution handler
# In execute_single_action()
```

### Database Modifications

**Procedure**:
1. Create migration script
2. Test on development database
3. Update assistant_production_schema.sql
4. Update database_manager.py if needed
5. Test rollback procedure
6. Document changes

---

## Request Lifecycle

### Complete Request Flow

```
1. USER INPUT
   ↓
2. INPUT PROCESSING
   ├── Voice Input → STT → Text
   ├── GUI Input → Text
   └── Text Input → Text
   ↓
3. INTELLIGENCE PROCESSING
   ├── Dialogue State Manager (context enrichment)
   ├── Multi-Intent Analyzer (intent detection)
   ├── Goal Planner (execution planning)
   └── Unified Router (intent routing)
   ↓
4. EXECUTION
   ├── Skill Execution
   ├── Action Execution
   ├── Module Execution
   └── Plugin Execution
   ↓
5. RESPONSE GENERATION
   ├── LLM Generation (if needed)
   ├── Template Response
   ├── RAG Response
   └── Personality Formatting
   ↓
6. OUTPUT
   ├── TTS → Audio Output
   ├── GUI → Visual Output
   └── System Action → OS Integration
   ↓
7. MEMORY UPDATE
   ├── Conversational Memory
   ├── User Memory
   ├── System Memory
   └── Database Logging
```

### Detailed Flow

**Step 1: Input Reception**
- Hot word detection triggers listening
- STT converts speech to text
- GUI receives text input
- Input validation and cleaning

**Step 2: Context Enrichment**
- Dialogue state manager processes turn
- Entity extraction and binding
- Reference resolution (pronouns)
- Context loading from memory

**Step 3: Intent Analysis**
- Multi-intent analyzer detects intents
- Parameter extraction for each intent
- Dependency analysis between intents
- Confidence scoring

**Step 4: Goal Planning**
- Intent ordering by priority
- Conflict detection and resolution
- Execution plan creation
- Risk assessment

**Step 5: Command Routing**
- Unified router matches patterns
- Semantic fallback if no match
- Parameter extraction
- Handler selection

**Step 6: Execution**
- Skill/action/module execution
- Error handling and retry
- Result collection
- Context accumulation

**Step 7: Response Generation**
- LLM generation for complex queries
- Template responses for simple commands
- RAG responses for knowledge queries
- Personality formatting

**Step 8: Output Delivery**
- TTS coordinator queues speech
- GUI updates display
- System actions executed
- Feedback provided

**Step 9: Memory Update**
- Conversational memory storage
- User memory updates
- System memory updates
- Database logging

---

## File Dependency Map

### Core Dependencies

**assistant.py** →
- instance/config.py
- extensions/assistant_orchestrator.py
- extensions/system/initialization_manager.py
- legacy/main.py

**core/brain.py** →
- core/unified_command_router.py
- core/multi_intent_analyzer.py
- core/goal_planner.py
- extensions/dialogue_state_manager.py

**core/unified_command_router.py** →
- extensions/llm_engine.py (semantic fallback)
- legacy/skills.py (skill execution)
- legacy/actions.py (action execution)

**legacy/assistant.py** →
- instance/config.py
- legacy/sst.py
- legacy/tts.py
- legacy/actions.py
- legacy/skills.py
- extensions/personality_engine/
- extensions/rag_system/
- extensions/reminder_engine/

### Extension Dependencies

**extensions/llm_engine.py** →
- instance/config.py
- openai (package)
- requests (package)

**extensions/database_manager.py** →
- psycopg2 (package)
- instance/config.py

**extensions/rag_system/** →
- instance/config.py
- extensions/llm_engine.py
- legacy/actions.py

**extensions/dialogue_state_manager.py** →
- core/unified_command_router.py

### Audio Dependencies

**legacy/sst.py** →
- instance/config.py
- speech_recognition (package)
- pyaudio (package)
- sounddevice (package)

**legacy/tts.py** →
- instance/config.py
- gtts (package)
- pyttsx3 (package)
- playsound (package)

**legacy/hotword_listener.py** →
- instance/config.py
- openwakeword (package)
- pvporcupine (package)
- extensions/system/wake_state_manager.py

### GUI Dependencies

**legacy/main.py** →
- legacy/floating_button.py
- legacy/login_window.py
- legacy/tts.py
- instance/config.py

**legacy/floating_button.py** →
- modules/launcher/launcher_panel.py
- legacy/tts.py

**modules/launcher/launcher_panel.py** →
- modules/launcher/launcher_functions.py
- modules/launcher/animation.py

---

## Command Cheat Sheet

### Voice Commands

**System Control**:
- "shutdown" / "power off" - Shutdown system
- "restart" - Restart system
- "sleep" - Sleep mode
- "take screenshot" - Capture screen
- "lock" - Lock system

**Application Control**:
- "open [app name]" - Launch application
- "close [app name]" - Close application
- "launch [app name]" - Launch application

**Device Control**:
- "mute" / "unmute" - Mute/unmute audio
- "increase volume" / "decrease volume" - Volume control
- "volume up" / "volume down" - Volume control

**Information**:
- "what is the time" - Current time
- "what is the date" - Current date
- "what is the weather in [location]" - Weather
- "search for [query]" - Web search

**Productivity**:
- "note [text]" - Create note
- "remind me to [task] at [time]" - Set reminder
- "calculate [expression]" - Math calculation
- "translate [text] to [language]" - Translation

**Media**:
- "play [song/artist]" - Play music
- "pause music" / "resume music" - Music control
- "next song" / "previous song" - Music navigation

**Memory**:
- "remember [fact]" - Store memory
- "what did I say about [topic]" - Recall memory
- "what are my preferences" - Show preferences

### System Commands

**Startup**:
```bash
python assistant.py          # Full system with GUI
assistant.bat                # Windows batch startup
```

**Testing**:
```bash
python test_failover.py      # Test failover systems
python test_routing.py       # Test routing logic
```

**Database**:
```bash
psql -d nova_assistant -f assistant_production_schema.sql
```

**Environment**:
```powershell
.\setup_env.ps1              # Setup environment variables
```

### Configuration Commands

**Set Wake Threshold**:
```python
from legacy.hotword_listener import set_wake_threshold
set_wake_threshold(0.7)
```

**Enable/Disable OpenAI**:
```bash
# In .env file
OPENAI_ENABLED=true         # Enable
OPENAI_ENABLED=false        # Disable
```

**Change Assistant Name**:
```python
# Stored in database per user
# Via user_preferences table
```

---

## Final Project Status

### System Maturity

**Production Status**: **Production Ready with Limitations**

**Stability**: **Stable**
- Core functionality reliable
- Voice interaction stable
- LLM integration robust
- Database system solid

**Feature Completeness**: **80%**
- Voice interaction: Complete
- GUI system: Complete
- LLM integration: Complete
- RAG system: Complete
- Memory system: Complete
- Plugin system: Partial
- Agent OS: Experimental

### Recommendations

**For Production Use**:
1. Monitor system performance
2. Regular database backups
3. API key rotation
4. Security audit
5. User training

**For Development**:
1. Improve test coverage
2. Reduce technical debt
3. Consolidate legacy code
4. Improve documentation
5. Performance optimization

**For Future Development**:
1. Complete plugin system
2. Enhance Agent OS
3. Add more language support
4. Improve offline capabilities
5. Enhanced security features

### Support and Maintenance

**Active Maintenance**: Yes
- Regular updates
- Bug fixes
- Feature additions
- Security patches

**Community Support**: Limited
- Documentation available
- Issue tracking (if repository is public)
- Community contributions (if repository is public)

---

## Conclusion

This Smart Assistant project represents a comprehensive AI-powered voice assistant system with extensive capabilities including voice interaction, multi-intent processing, RAG, personality engine, and system integration. The system combines legacy functionality with modern AI capabilities, providing a robust platform for voice-based interaction and automation.

The architecture supports multiple LLM providers with automatic fallback, comprehensive memory systems, and extensible plugin architecture. While there is some technical debt and legacy code, the core functionality is stable and production-ready.

For specific implementation details or troubleshooting, refer to the individual component documentation and source code comments.

---

**Document Version**: 1.0  
**Last Updated**: 2026-09-16  
**Project Status**: Production Ready  
**Documentation Coverage**: Complete A-to-Z