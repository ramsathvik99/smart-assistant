# Smart Assistant

An advanced AI-powered voice assistant with proactive intelligence, multi-intent understanding, and comprehensive system automation capabilities. Built with Python, PyQt6, and multiple LLM providers, it features continuous voice interaction, visual response surfaces, and a sophisticated execution pipeline.

## Overview

Smart Assistant is a production-grade voice AI system that combines:
- **Voice-first interaction** with continuous microphone listening, VAD speech detection, and true barge-in support
- **Multi-provider LLM support** (OpenAI, Groq, Gemini, DeepSeek, HuggingFace, Anthropic, Ollama) with automatic failover
- **Proactive intelligence** that observes your environment and offers contextually relevant assistance
- **Deterministic intent routing** with 18-level priority classification and semantic fallback
- **Comprehensive automation** including browser control, document generation, smart home management, calendar integration, and more
- **Multi-user architecture** with PostgreSQL persistence, per-user isolation, and long-term memory
- **Professional document generation** (PDF, DOCX, PPTX, XLSX) with AI-powered content
- **Rich PyQt6 UI** with floating launcher, dashboard, and visual response surfaces

## Key Features

### Core Intelligence
- **Unified Command Router**: Deterministic regex-based intent routing with 18 strict priorities
- **Multi-Intent Analyzer**: Detects and handles multiple commands in a single utterance
- **Goal Planner**: Transforms intents into executable plans with conflict detection and risk assessment
- **Semantic Understanding**: LLM-powered intent classification for complex or ambiguous requests
- **Proactive Observer**: Monitors environment state and offers relevant assistance without explicit requests
- **Outcome Verifier**: Validates execution results and implements adaptive recovery

### Voice & Audio
- **Continuous microphone listening** with persistent audio stream
- **Neural VAD (Voice Activity Detection)** for accurate speech detection
- **Local Whisper STT engine** with startup pre-warming for instant first command
- **Neural TTS** with pluggable providers (Edge TTS, OpenAI, SAPI fallback)
- **True barge-in/interruption** - interrupt the assistant mid-sentence
- **Intelligent audio ducking** for music/media playback during speech
- **No mandatory wake word** - assistant-name recognition is optional and adaptive

### Multi-Provider LLM Engine
- **OpenAI** (GPT-4o-mini, GPT-4o, etc.)
- **Groq** (Qwen, GPT-OSS models) with ultra-low latency
- **Google Gemini** (Gemini 2.5 Flash)
- **DeepSeek** (DeepSeek Chat, DeepSeek Flash)
- **HuggingFace** (Mistral, LLaMA, and custom models)
- **Anthropic** (Claude 3.5 Sonnet)
- **Ollama** (local LLM hosting)
- **Automatic failover** across multiple API keys per provider
- **Latency-optimized racing** with hedged requests for speed

### Automation Modules
- **Browser Control**: Navigate, search, and interact with web pages
- **Document Generation**: Create professional PDFs, DOCX, PPTX, XLSX with AI content
- **Calendar & Reminders**: Event management, daily briefings, recurring events
- **Email**: Read, compose, and send emails with AI assistance
- **Music/Media**: YouTube playback, music streaming with audio ducking
- **System Controller**: File management, app launching, desktop organization
- **Smart Home**: Device discovery, control, and automation
- **Window Management**: Arrange, minimize, maximize windows contextually
- **Clipboard**: Smart clipboard analysis and history
- **Task Management**: Queue-based task execution with error recovery
- **Code Generation**: AI-powered code generation and editing
- **Device Management**: Android device control, file transfer, audio routing
- **Learning**: User preference learning and rule adaptation
- **Undo**: Reverse actions with full history tracking

### UI & Presentation
- **PyQt6 Assistant UI**: Modern, responsive interface
- **Floating Launcher**: Always-accessible quick-action panel
- **Dashboard**: Comprehensive view of assistant state, calendar, settings
- **Visual Response Surface**: Displays structured data, tables, lists visually
- **Visual Response Cache**: "Show that again" capability
- **Outside-click dismissal**: Natural interaction patterns
- **Account-specific assistant name**: Personalization per user

### Data & Persistence
- **PostgreSQL Database**: Robust multi-user data persistence
- **19 Migration Steps**: Evolved schema with full backward compatibility
- **Long-term Memory**: Automatic context-aware fact extraction and retention
- **Conversational Memory**: Full chat history with semantic search
- **Execution Records**: Tracks all actions with causal attribution
- **User Isolation**: Complete data separation per authenticated user
- **pgvector Support**: Semantic similarity search for memory

### Security & Reliability
- **Authentication**: User login with password hashing
- **Permission Management**: Capability consent system
- **Risk Policy Engine**: Evaluates and blocks dangerous operations
- **Audit Logging**: Security audit logs for all sensitive actions
- **Elevation Coordination**: Handles Windows UAC prompts gracefully
- **Single-Instance Lock**: Prevents duplicate assistant processes
- **Regression Protection**: Strict development rules prevent breaking changes

## Technology Stack

### Core
- **Python 3.x**: Primary language
- **PyQt6**: Desktop UI framework
- **PostgreSQL**: Database with psycopg2-binary
- **python-dotenv**: Environment configuration

### AI/ML
- **OpenAI API**: GPT models
- **Groq API**: Low-latency inference
- **Google Gemini API**: Gemini models
- **DeepSeek API**: DeepSeek models
- **HuggingFace API**: Model inference
- **Anthropic API**: Claude models
- **Ollama**: Local LLM hosting
- **faster-whisper**: Local STT (Speech-to-Text)
- **onnxruntime**: Model runtime
- **pgvector**: Vector similarity search

### Audio/Voice
- **pyttsx3**: TTS fallback
- **pyaudio**: Audio input/output
- **soundfile**: Audio file handling
- **simpleaudio**: Audio playback
- **gTTS**: Google TTS
- **playsound**: Sound effects

### Automation
- **pyautogui**: GUI automation
- **pyperclip**: Clipboard access
- **psutil**: System information
- **plyer**: Cross-platform APIs
- **requests**: HTTP client
- **beautifulsoup4**: Web scraping
- **yt-dlp**: YouTube/media download
- **feedparser**: RSS/Atom feeds

### Data Processing
- **numpy**: Numerical computing
- **geopy**: Geocoding
- **timezonefinder**: Timezone detection
- **deep-translator**: Multilingual translation
- **wikipedia**: Wikipedia API
- **speedtest-cli**: Network speed testing

### Document Generation
- **python-docx**: DOCX generation
- **reportlab**: PDF generation
- **python-pptx**: PPTX generation
- **openpyxl**: XLSX generation

## Architecture

### High-Level Flow

```
USER INPUT (Voice/Text)
    ↓
STT (Whisper) / Text Processing
    ↓
INTENT RESOLUTION
    ├─ Deterministic Regex (Fast Path - 18 priorities)
    └─ Semantic Fallback (LLM Classification)
    ↓
UNIFIED COMMAND ROUTER
    ↓
MULTI-INTENT ANALYZER
    ↓
GOAL PLANNER
    ↓
MODULE EXECUTION
    ↓
OUTCOME VERIFICATION
    ↓
CONTEXT UPDATE
    ↓
RESPONSE (TTS + Visual Surface)
```

### Key Components

#### Core Intelligence (`core/`)
- **unified_command_router.py**: Deterministic intent routing with priority classification
- **goal_planner.py**: Transforms intents into executable plans
- **multi_intent_analyzer.py**: Detects multiple commands in single utterance
- **semantic_understanding.py**: LLM-powered semantic intent classification
- **proactive_observer.py**: Environment monitoring and proactive suggestions
- **environment_observer.py**: Desktop environment state tracking
- **outcome_verifier.py**: Execution validation and adaptive recovery
- **risk_policy_engine.py**: Dangerous operation evaluation
- **fact_extractor.py**: Automatic fact extraction for long-term memory
- **model_registry.py**: LLM provider management and failover
- **llm_health.py**: Provider health monitoring

#### Extensions (`extensions/`)
- **llm_engine.py**: Multi-provider LLM interface with racing and failover
- **memory_store.py**: Long-term memory with pgvector semantic search
- **dialogue_state_manager.py**: Conversation state management
- **context_manager.py**: Context tracking and retrieval
- **database_manager.py**: PostgreSQL connection pool and queries
- **personality_engine/**: Response formatting and behavior layer
- **rag_system/**: Retrieval-augmented generation for knowledge
- **reminder_engine/**: Reminder scheduling and notification
- **weather_engine.py**: Weather information integration

#### Modules (`modules/`)
- **browser/**: Web browser control and automation
- **document_tools/**: PDF, DOCX, PPTX, XLSX generation
- **calendar_manager/**: Event management and daily briefings
- **assistant_email/**: Email reading, composing, sending
- **music/**: Music and media playback
- **system_controller/**: File management, app launching
- **ui/**: PyQt6 UI components and dashboard
- **code_generator/**: AI-powered code generation

#### Skills (`skills/`)
- **audio_management/**: Audio device control and ducking
- **device_management/**: Android device control
- **smart_home/**: Smart home device management
- **window_management/**: Window arrangement and control
- **clipboard/**: Clipboard analysis and history
- **learning/**: User preference learning
- **undo/**: Action reversal
- **task_management/**: Task queue and error recovery

## Project Structure

```
smart_assistant/
├── assistant.py                      # Main entry point
├── requirements.txt                  # Python dependencies
├── .env.example                      # Environment configuration template
├── .gitignore                        # Git ignore rules
├── AGENTS.md                         # Development rules and regression protection
├── assistant_production_schema.sql   # Reference database schema
├── instance/
│   └── config.py                     # Centralized configuration
├── core/                             # Intelligence engine
│   ├── unified_command_router.py
│   ├── goal_planner.py
│   ├── multi_intent_analyzer.py
│   ├── proactive_observer.py
│   ├── environment_observer.py
│   ├── outcome_verifier.py
│   ├── model_registry.py
│   ├── llm_health.py
│   ├── fact_extractor.py
│   ├── risk_policy_engine.py
│   ├── semantic_understanding.py
│   ├── os_gateway/                   # OS operation abstraction
│   └── environment/                  # Environment observation adapters
├── extensions/                       # Supporting systems
│   ├── llm_engine.py
│   ├── memory_store.py
│   ├── dialogue_state_manager.py
│   ├── context_manager.py
│   ├── database_manager.py
│   ├── personality_engine/
│   ├── rag_system/
│   ├── reminder_engine/
│   └── system/
├── modules/                          # Feature modules
│   ├── browser/
│   ├── document_tools/
│   ├── calendar_manager/
│   ├── assistant_email/
│   ├── music/
│   ├── system_controller/
│   ├── ui/
│   └── code_generator/
├── skills/                           # Specialized capabilities
│   ├── audio_management/
│   ├── device_management/
│   ├── smart_home/
│   ├── window_management/
│   ├── clipboard/
│   ├── learning/
│   ├── undo/
│   └── task_management/
├── migrations/                       # Database schema migrations
│   ├── 000_initial_base_schema.sql
│   ├── 001_multi_user_and_memory_architecture.sql
│   ├── 002_remove_plaintext_password_column.sql
│   ├── 003_pgvector_semantic_memory.sql
│   ├── 004_execution_experience_memory.sql
│   ├── 005_strategy_learning_signals.sql
│   ├── 006_environment_awareness.sql
│   ├── 007_os_action_history.sql
│   ├── 008_execution_graphs_and_action_records.sql
│   ├── 009_concurrent_tasks_and_events.sql
│   ├── 010_document_intelligence.sql
│   ├── 011_professional_document_engine.sql
│   ├── 012_causal_state_events.sql
│   ├── 013_content_artifacts_and_insertions.sql
│   ├── 014_artifact_reading_sessions.sql
│   ├── 015_user_api_credentials.sql
│   ├── 016_calendar_expansion.sql
│   ├── 017_capability_consents.sql
│   ├── 018_concurrency_safe_reminders.sql
│   └── 019_automatic_context_aware_memory.sql
├── data/                             # Runtime data
│   ├── llm_provider_health.json
│   ├── location/
│   └── user_preferences.json
├── tools/                            # Validation and benchmarking tools
├── legacy/                           # Legacy code (being phased out)
└── venv/                             # Virtual environment (gitignored)
```

## Prerequisites

### Runtime Requirements
- **Python 3.8+** (recommended: Python 3.10 or 3.11)
- **PostgreSQL 12+** with pgvector extension
- **Windows 10/11** (primary platform)
- **Microphone** for voice input
- **Speakers** for voice output

### Hardware Requirements
- **CPU**: Modern multi-core processor (Intel i5+/AMD Ryzen 5+ recommended)
- **RAM**: 8GB minimum, 16GB recommended
- **Storage**: 5GB free space (for models and dependencies)
- **GPU**: Optional (for local LLMs via Ollama)

### External Services
- **OpenAI API key** (or alternative LLM provider)
- **SerpAPI key** (for web search)
- **Weather API key** (for weather information)
- **Calendarific API key** (optional, for holidays)

### System Dependencies (Windows)
- **Microsoft Visual C++ Redistributable** (for pyaudio)
- **PostgreSQL ODBC Driver** (if using external DB tools)

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/ramsathvik99/smart-assistant.git
cd smart-assistant
```

### 2. Create Virtual Environment

```bash
python -m venv venv
venv\Scripts\activate  # On Windows
# or
source venv/bin/activate  # On Linux/Mac
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

**Note:** On Windows, if `pyaudio` installation fails, you may need to:
```bash
pip install pipwin
pipwin install pyaudio
```

### 4. Configure Environment Variables

Copy the example environment file:
```bash
copy .env.example .env  # On Windows
# or
cp .env.example .env  # On Linux/Mac
```

Edit `.env` and configure your API keys and settings:

```env
# Assistant Name
ASSISTANT_NAME=Trevon

# Database (PostgreSQL)
DB_HOST=localhost
DB_PORT=5432
DB_NAME=assistant_db
DB_USER=postgres
DB_PASSWORD=your_postgres_password

# LLM Providers (configure at least one)
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-4o-mini
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=qwen/qwen3.8-27b
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.5-flash
DEEPSEEK_API_KEY=your_deepseek_api_key
DEEPSEEK_MODEL=deepseek-chat

# Search & External Services
SERPAPI_API_KEY=your_serpapi_api_key
WEATHER_API_KEY=your_weather_api_key
```

### 5. Initialize PostgreSQL Database

Ensure PostgreSQL is running and pgvector extension is installed:

```sql
-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;
```

Run database migrations:

```bash
python core/migration_runner.py
```

This will apply all 19 migrations to create the canonical schema.

### 6. Download Speech Models (Optional)

The assistant uses `faster-whisper` for local STT. Models are downloaded automatically on first use. To pre-download:

```bash
python -c "from faster_whisper import WhisperModel; WhisperModel('small')"
```

### 7. Start the Assistant

```bash
python assistant.py
```

The assistant will:
1. Initialize core services
2. Start the PyQt6 UI
3. Begin continuous microphone listening
4. Load your user preferences

## Usage

### Voice Interaction

Simply speak to the assistant. Examples:

- "What's the weather today?"
- "Open my email"
- "Create a PDF report on quarterly sales"
- "Play some music"
- "Remind me to call John at 3 PM"
- "What's on my calendar tomorrow?"
- "Open YouTube and search for Python tutorials"
- "Minimize all windows except this one"
- "Turn on the living room lights" (requires smart home setup)

### Text Interaction

You can also type commands in the UI's command bar.

### Floating Launcher

Double-click the floating launcher button to:
- Quick actions
- Voice panel
- Settings
- System menu

### Dashboard

Access the dashboard for:
- Calendar view
- Assistant orb visualization
- Settings configuration
- Memory browser
- Connected devices
- Task queue

### Visual Responses

The assistant displays structured data visually:
- Tables for data
- Lists for items
- Cards for rich content
- Charts when applicable

Say "show that again" to redisplay the last visual response.

## Environment Variables

See `.env.example` for the complete list. Key variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `ASSISTANT_NAME` | No | Custom assistant name (default: Trevon) |
| `DB_HOST` | Yes | PostgreSQL host |
| `DB_PORT` | Yes | PostgreSQL port (default: 5432) |
| `DB_NAME` | Yes | Database name |
| `DB_USER` | Yes | PostgreSQL user |
| `DB_PASSWORD` | Yes | PostgreSQL password |
| `OPENAI_API_KEY` | No* | OpenAI API key (or another provider) |
| `GROQ_API_KEY` | No* | Groq API key |
| `GEMINI_API_KEY` | No* | Google Gemini API key |
| `DEEPSEEK_API_KEY` | No* | DeepSeek API key |
| `HF_API_KEY` | No* | HuggingFace API key |
| `ANTHROPIC_API_KEY` | No* | Anthropic API key |
| `SERPAPI_API_KEY` | Yes | SerpAPI key for web search |
| `WEATHER_API_KEY` | Yes | Weather API key |
| `TTS_PROVIDER` | No | TTS provider: neural, edge, openai, sapi |
| `STT_ENGINE` | No | STT engine: whisper (default) |
| `VOICE_ENGINE` | No | Voice engine: pyttsx3 (default) |

*At least one LLM provider key is required.

## Database Schema

The project uses PostgreSQL with the following major tables:

### Core Tables
- **users**: User accounts with authentication
- **user_memory**: Legacy JSONB memory model
- **user_preferences**: Per-user settings
- **system_memory**: Key-value system state
- **conversations**: Full chat history
- **memory_facts**: Semantic fact extraction with pgvector

### Automation Tables
- **reminders**: Task reminders with notification status
- **calendar_events**: Calendar events and reminders
- **recurrence_rules**: Recurring event patterns
- **calendar_settings**: Per-user calendar preferences

### Intelligence Tables
- **execution_records**: Action execution history
- **os_action_history**: OS operations with causal attribution
- **execution_graphs**: Multi-step execution plans
- **strategy_learning_signals**: Learning feedback signals
- **content_artifacts**: Generated document artifacts

### Security Tables
- **security_audit_logs**: Security event logging
- **capability_consents**: User permission grants
- **user_api_credentials**: Encrypted third-party API keys

See `assistant_production_schema.sql` for the complete canonical schema reference.

## Testing

Run the test suite:

```bash
pytest
```

Run specific test modules:

```bash
pytest skills/audio_management/test_audio_interaction_integration.py
```

Run with coverage:

```bash
pytest --cov=core --cov=extensions --cov=modules
```

## Troubleshooting

### Common Issues

**PostgreSQL Connection Failed**
- Ensure PostgreSQL is running
- Check DB_HOST, DB_PORT, DB_USER, DB_PASSWORD in .env
- Verify pgvector extension is installed: `CREATE EXTENSION vector;`

**PyAudio Installation Failed (Windows)**
```bash
pip install pipwin
pipwin install pyaudio
```

**Microphone Not Detected**
- Check Windows privacy settings for microphone access
- Ensure no other application is using the microphone
- Verify your default recording device in Windows Sound settings

**LLM API Timeout**
- Check your API key is valid
- Verify network connectivity
- Increase `LLM_REQUEST_TIMEOUT` in .env
- Configure multiple API keys for failover

**Whisper Model Download Slow**
- Pre-download models manually
- Use a smaller model (e.g., `tiny` instead of `small`)
- Set `STT_MODEL=tiny` in .env

**Database Migration Failed**
- Check PostgreSQL version (12+ required)
- Verify pgvector is installed
- Check database permissions
- Review migration logs in console output

## Security Considerations

### Secrets Management
- **Never commit** `.env` files to version control
- **Never commit** API keys, passwords, or tokens
- Use `.env.example` as a template only
- Rotate API keys if accidentally exposed

### User Isolation
- Each user has complete data separation
- All queries scoped to `CURRENT_USER_ID`
- No cross-user data access
- Foreign key constraints enforce isolation

### Risk Evaluation
- The `risk_policy_engine` evaluates dangerous operations
- File deletions require confirmation
- System commands are sanitized
- OS operations are logged in `security_audit_logs`

### Permissions
- Capability consent system for sensitive features
- User must grant permission for:
  - Smart home control
  - Device management
  - File system access
  - External API usage

### Audit Logging
- All security-sensitive actions are logged
- Logs include: user_id, action, params, status, timestamp
- Review `security_audit_logs` table for audit trail

## Development

### Regression Protection

This project follows strict regression protection rules documented in `AGENTS.md`. Key principles:

1. **DO NOT** assume existing architecture is wrong
2. **DO NOT** broadly refactor shared systems
3. **DO NOT** rewrite `UnifiedCommandRouter`, `GoalPlanner`, or `DialogueStateManager`
4. **DO NOT** modify working audio/STT/VAD/TTS/barge-in behavior
5. **DO NOT** modify PostgreSQL schema without explicit proof of necessity
6. **DO NOT** change unrelated modules while fixing one module
7. **If a regression occurs, STOP and fix before continuing**

### Production Path Tracing

Before modifying code, trace the exact failure through:
```
INPUT → INTENT → ROUTER → PLANNER → MODULE → EXECUTION → VERIFICATION → CONTEXT → RESPONSE
```

### Protected Capabilities

The following capabilities are frozen baseline functionality:
- Continuous microphone listening
- VAD speech detection
- STT/TTS with barge-in
- Intent resolution and routing
- Multi-intent handling
- Goal lifecycle management
- Proactive environment observation
- Document generation
- PostgreSQL persistence
- User authentication and isolation

See `AGENTS.md` for the complete protected capability baseline.

## Roadmap

The project is in a mature integration and hardening stage. Future improvements may include:

- Enhanced mobile app integration
- Additional smart home provider support
- Improved multilingual capabilities
- Advanced learning and personalization
- Plugin system for third-party extensions
- Cloud sync for user preferences
- Enhanced document templates
- More sophisticated proactive intelligence

## Contributing

Contributions are welcome but must follow the regression protection rules in `AGENTS.md`. Before contributing:

1. Read `AGENTS.md` thoroughly
2. Trace the production path for your intended change
3. Identify the exact component to modify
4. Ensure the change is isolated and scoped
5. Run regression tests for affected capabilities
6. Verify no existing functionality is broken

## License

This project is private. Do not assume open-source licensing without explicit authorization.

## Acknowledgments

Built with:
- OpenAI, Groq, Google, DeepSeek, HuggingFace, Anthropic for LLM APIs
- PostgreSQL for robust data persistence
- PyQt6 for modern desktop UI
- Faster-Whisper for efficient speech recognition
- The open-source Python community

## Contact

Repository: https://github.com/ramsathvik99/smart-assistant

## Disclaimer

This is a personal project for educational and research purposes. Use at your own risk. The developers are not responsible for any damage or data loss caused by the assistant's automation capabilities. Always review automated actions before execution, especially for file deletions and system modifications.
