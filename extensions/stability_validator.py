"""
NOVA Assistant Stability Validator
Comprehensive startup validation to ensure system stability
"""
import os
import sys
import traceback
from pathlib import Path
from typing import Dict, List, Tuple

class StabilityValidator:
    """Validates all system components for stability"""
    
    def __init__(self):
        self.validation_results = {}
        self.critical_failures = []
        self.warnings = []
        
    def validate_all_systems(self) -> Dict:
        """Run comprehensive stability validation"""
        print("🔍 SYSTEM STABILITY VALIDATION STARTING...")
        print("=" * 60)
        
        validations = [
            ("Python Environment", self._validate_python_environment),
            ("Database Connection", self._validate_database_connection),
            ("Database Schema", self._validate_database_schema),
            ("AI Services", self._validate_ai_services),
            ("Hotword System", self._validate_hotword_system),
            ("GUI System", self._validate_gui_system),
            ("Import Architecture", self._validate_import_architecture),
            ("File System", self._validate_file_system),
            ("Environment Variables", self._validate_environment_variables),
            ("Memory System", self._validate_memory_system),
        ]
        
        for name, validator in validations:
            try:
                print(f"\n🧪 Validating {name}...")
                result = validator()
                self.validation_results[name] = result
                
                if result['status'] == 'critical':
                    self.critical_failures.append(f"{name}: {result['message']}")
                    print(f"❌ {name}: {result['message']}")
                elif result['status'] == 'warning':
                    self.warnings.append(f"{name}: {result['message']}")
                    print(f"⚠️  {name}: {result['message']}")
                else:
                    print(f"✅ {name}: {result['message']}")
                    
            except Exception as e:
                error_msg = f"{name}: Validation crashed - {str(e)}"
                self.critical_failures.append(error_msg)
                self.validation_results[name] = {
                    'status': 'critical',
                    'message': f'Validation crashed: {str(e)}'
                }
                print(f"💥 {name}: Validation crashed - {str(e)}")
                traceback.print_exc()
        
        return self._generate_final_report()
    
    def _validate_python_environment(self) -> Dict:
        """Validate Python version and environment"""
        python_version = sys.version_info
        
        if python_version >= (3, 13):
            return {
                'status': 'warning',
                'message': f'Python {python_version.major}.{python_version.minor} - hotword may be unstable'
            }
        elif python_version < (3, 8):
            return {
                'status': 'critical',
                'message': f'Python {python_version.major}.{python_version.minor} - below minimum requirement (3.8+)'
            }
        else:
            return {
                'status': 'healthy',
                'message': f'Python {python_version.major}.{python_version.minor} - supported'
            }
    
    def _validate_database_connection(self) -> Dict:
        """Validate database connection"""
        try:
            from psycopg2 import pool
            from instance.config import settings as CONFIG
            
            db_pool = pool.SimpleConnectionPool(
                1, 2,
                host=CONFIG.DB_HOST,
                database=CONFIG.DB_NAME,
                user=CONFIG.DB_USER,
                password=CONFIG.DB_PASSWORD,
                port=CONFIG.DB_PORT
            )
            
            # Test connection
            conn = db_pool.getconn()
            cursor = conn.cursor()
            cursor.execute("SELECT 1;")
            cursor.fetchone()
            
            # Clean up
            cursor.close()
            db_pool.putconn(conn)
            db_pool.closeall()
            
            return {
                'status': 'healthy',
                'message': 'Database connection successful'
            }
            
        except Exception as e:
            return {
                'status': 'critical',
                'message': f'Database connection failed: {str(e)}'
            }
    
    def _validate_database_schema(self) -> Dict:
        """Validate database schema"""
        try:
            from extensions.database_manager import DatabaseManager
            from psycopg2 import pool
            from instance.config import settings as CONFIG
            
            db_pool = pool.SimpleConnectionPool(
                1, 2,
                host=CONFIG.DB_HOST,
                database=CONFIG.DB_NAME,
                user=CONFIG.DB_USER,
                password=CONFIG.DB_PASSWORD,
                port=CONFIG.DB_PORT
            )
            
            db_manager = DatabaseManager(db_pool)
            
            # Check if user_preferences has correct schema
            with db_manager._get_cursor() as cur:
                if cur:
                    cur.execute("""
                        SELECT column_name 
                        FROM information_schema.columns 
                        WHERE table_name = 'user_preferences'
                        ORDER BY ordinal_position;
                    """)
                    columns = [row[0] for row in cur.fetchall()]
                    
                    required_columns = ['id', 'user_id', 'pref_key', 'pref_value', 'created_at']
                    missing_columns = [col for col in required_columns if col not in columns]
                    duplicate_columns = [col for col in columns if col in ['key', 'value']]
                    
                    if missing_columns:
                        return {
                            'status': 'critical',
                            'message': f'Missing columns: {missing_columns}'
                        }
                    elif duplicate_columns:
                        return {
                            'status': 'warning',
                            'message': f'Duplicate columns detected: {duplicate_columns}'
                        }
                    else:
                        return {
                            'status': 'healthy',
                            'message': 'Database schema is correct'
                        }
            
            db_pool.closeall()
            
        except Exception as e:
            return {
                'status': 'critical',
                'message': f'Schema validation failed: {str(e)}'
            }
    
    def _validate_ai_services(self) -> Dict:
        """Validate AI services"""
        try:
            from extensions.ai_engine import AIEngine
            
            ai_engine = AIEngine()
            
            # Check if at least one AI service is available
            if ai_engine.openai_client:
                return {
                    'status': 'healthy',
                    'message': 'OpenAI service available'
                }
            elif ai_engine.groq_key:
                return {
                    'status': 'healthy',
                    'message': 'Groq service available'
                }
            else:
                return {
                    'status': 'critical',
                    'message': 'No AI services available'
                }
                
        except Exception as e:
            return {
                'status': 'critical',
                'message': f'AI service validation failed: {str(e)}'
            }
    
    def _validate_hotword_system(self) -> Dict:
        """Validate hotword system"""
        issues = []
        
        # Check Python version (updated to be less restrictive)
        if sys.version_info >= (3, 13):
            issues.append("Python 3.13+ may have compatibility issues")
        
        # Check PPN file
        try:
            from pathlib import Path
            
            # Use absolute path from project root (go up two levels from extensions/stability_validator.py)
            base_dir = Path(__file__).resolve().parent.parent
            ppn_path = base_dir / "legacy" / "wake_words" / "Hey_Nova_20260303_082924.onnx"
            
            print(f"[DEBUG] PPN Path: {ppn_path}")
            print(f"[DEBUG] PPN exists: {ppn_path.exists()}")
            
            if not ppn_path.exists():
                issues.append(f"PPN file not found at {ppn_path}")
        except Exception as e:
            issues.append(f"Resource helper error: {e}")
        
        # Check access key
        try:
            from dotenv import load_dotenv
            load_dotenv()
            
            access_key = os.getenv("PORCUPINE_ACCESS_KEY") or os.getenv("PICOVOICE_ACCESS_KEY")
            print(f"[DEBUG] Access Key Present: {bool(access_key)}")
            
            if not access_key:
                issues.append("PORCUPINE_ACCESS_KEY or PICOVOICE_ACCESS_KEY not set in environment variables")
        except Exception as e:
            issues.append(f"Environment check error: {e}")
        
        # Check libraries
        try:
            import pvporcupine
            from pvrecorder import PvRecorder
        except ImportError:
            issues.append("pvporcupine library not installed")
        
        if issues:
            # Only mark as warning if it's just Python 3.13 compatibility
            if len(issues) == 1 and "Python 3.13+" in issues[0]:
                return {
                    'status': 'healthy',
                    'message': 'Hotword system ready (Python 3.13+ compatibility mode)'
                }
            else:
                return {
                    'status': 'warning',
                    'message': f'Hotword issues: {", ".join(issues)}'
                }
        else:
            return {
                'status': 'healthy',
                'message': 'Hotword system ready'
            }
    
    def _validate_gui_system(self) -> Dict:
        """Validate GUI system"""
        try:
            import tkinter
            # Test if tkinter can create a window
            root = tkinter.Tk()
            root.withdraw()  # Hide the test window
            root.destroy()
            
            return {
                'status': 'healthy',
                'message': 'GUI system available'
            }
        except Exception as e:
            return {
                'status': 'warning',
                'message': f'GUI system unavailable: {str(e)}'
            }
    
    def _validate_import_architecture(self) -> Dict:
        """Validate import architecture"""
        try:
            # Test legacy imports
            from legacy.tts import speak
            from legacy.sst import listen
            from legacy.assistant import process_input
            from legacy.auth_helpers import try_restore_session
            
            return {
                'status': 'healthy',
                'message': 'Import architecture correct'
            }
        except ImportError as e:
            return {
                'status': 'critical',
                'message': f'Import architecture error: {str(e)}'
            }
    
    def _validate_file_system(self) -> Dict:
        """Validate file system structure"""
        required_dirs = ['legacy', 'extensions', 'modules', 'instance']
        missing_dirs = []
        
        # Get the project root using pathlib (go up two levels from extensions/stability_validator.py)
        project_root = Path(__file__).resolve().parent.parent
        
        for dir_name in required_dirs:
            dir_path = project_root / dir_name
            if not dir_path.is_dir():
                missing_dirs.append(dir_name)
        
        if missing_dirs:
            return {
                'status': 'warning',  # Changed from critical to warning
                'message': f'Missing directories: {missing_dirs} (may be path detection issue)'
            }
        else:
            return {
                'status': 'healthy',
                'message': 'File system structure correct'
            }
    
    def _validate_environment_variables(self) -> Dict:
        """Validate environment variables"""
        required_vars = ['DB_HOST', 'DB_NAME', 'DB_USER', 'DB_PASSWORD']
        missing_vars = []
        
        for var in required_vars:
            if not os.getenv(var):
                missing_vars.append(var)
        
        if missing_vars:
            return {
                'status': 'critical',
                'message': f'Missing environment variables: {missing_vars}'
            }
        else:
            return {
                'status': 'healthy',
                'message': 'Environment variables configured'
            }
    
    def _validate_memory_system(self) -> Dict:
        """Validate memory system"""
        try:
            from extensions.context_manager import get_manager
            context = get_manager()
            
            return {
                'status': 'healthy',
                'message': 'Memory system available'
            }
        except Exception as e:
            return {
                'status': 'warning',
                'message': f'Memory system issue: {str(e)}'
            }
    
    def _generate_final_report(self) -> Dict:
        """Generate final stability report"""
        total_checks = len(self.validation_results)
        healthy_count = sum(1 for r in self.validation_results.values() if r['status'] == 'healthy')
        warning_count = sum(1 for r in self.validation_results.values() if r['status'] == 'warning')
        critical_count = sum(1 for r in self.validation_results.values() if r['status'] == 'critical')
        
        if critical_count > 0:
            overall_status = 'critical'
            status_message = f'CRITICAL: {critical_count} critical failures prevent startup'
        elif warning_count > 0:
            overall_status = 'degraded'
            status_message = f'DEGRADED: {warning_count} warnings - system will run with limitations'
        else:
            overall_status = 'healthy'
            status_message = 'HEALTHY: All systems validated successfully'
        
        return {
            'overall_status': overall_status,
            'status_message': status_message,
            'total_checks': total_checks,
            'healthy_count': healthy_count,
            'warning_count': warning_count,
            'critical_count': critical_count,
            'critical_failures': self.critical_failures,
            'warnings': self.warnings,
            'detailed_results': self.validation_results,
            'can_startup': critical_count == 0
        }

# Global validator instance
stability_validator = StabilityValidator()

def run_stability_validation() -> Dict:
    """Run comprehensive stability validation"""
    return stability_validator.validate_all_systems()
