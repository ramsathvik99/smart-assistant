"""
Service Health Monitor for NOVA Assistant
Provides startup health checks, service isolation, and graceful failure handling
"""
import time
import traceback
from typing import Dict, List, Optional
from dataclasses import dataclass

@dataclass
class ServiceStatus:
    name: str
    status: str  # 'healthy', 'degraded', 'failed', 'disabled'
    message: str
    startup_time: float
    last_check: float
    critical: bool = True

class ServiceHealthMonitor:
    """Monitors and manages health of all NOVA services"""
    
    def __init__(self):
        self.services: Dict[str, ServiceStatus] = {}
        self.startup_time = time.time()
        self.critical_failures = []
        
    def register_service(self, name: str, critical: bool = True):
        """Register a service for monitoring"""
        self.services[name] = ServiceStatus(
            name=name,
            status='initializing',
            message='Service registered',
            startup_time=time.time(),
            last_check=time.time(),
            critical=critical
        )
        
    def update_service_status(self, name: str, status: str, message: str = ""):
        """Update service status"""
        if name in self.services:
            self.services[name].status = status
            self.services[name].message = message
            self.services[name].last_check = time.time()
            
            # Track critical failures
            if status == 'failed' and self.services[name].critical:
                self.critical_failures.append({
                    'service': name,
                    'message': message,
                    'timestamp': time.time()
                })
                
    def check_service_health(self, name: str, check_func) -> bool:
        """Run health check for a service"""
        if name not in self.services:
            return False
            
        try:
            result = check_func()
            if result:
                self.update_service_status(name, 'healthy', 'Health check passed')
                return True
            else:
                self.update_service_status(name, 'degraded', 'Health check failed')
                return False
        except Exception as e:
            self.update_service_status(name, 'failed', f'Health check error: {str(e)}')
            return False
            
    def get_startup_health_report(self) -> Dict:
        """Generate comprehensive startup health report"""
        total_time = time.time() - self.startup_time
        
        healthy = sum(1 for s in self.services.values() if s.status == 'healthy')
        degraded = sum(1 for s in self.services.values() if s.status == 'degraded')
        failed = sum(1 for s in self.services.values() if s.status == 'failed')
        disabled = sum(1 for s in self.services.values() if s.status == 'disabled')
        
        return {
            'startup_time_seconds': round(total_time, 2),
            'total_services': len(self.services),
            'services_status': {
                'healthy': healthy,
                'degraded': degraded,
                'failed': failed,
                'disabled': disabled
            },
            'critical_failures': len(self.critical_failures),
            'services': {name: {
                'status': service.status,
                'message': service.message,
                'critical': service.critical,
                'startup_time': round(service.startup_time - self.startup_time, 2)
            } for name, service in self.services.items()},
            'overall_health': self._calculate_overall_health()
        }
        
    def _calculate_overall_health(self) -> str:
        """Calculate overall system health"""
        if not self.services:
            return 'unknown'
            
        critical_failed = sum(1 for s in self.services.values() 
                            if s.status == 'failed' and s.critical)
        
        if critical_failed > 0:
            return 'critical'
        elif any(s.status == 'failed' for s in self.services.values()):
            return 'degraded'
        elif any(s.status == 'degraded' for s in self.services.values()):
            return 'degraded'
        else:
            return 'healthy'
            
    def print_health_report(self):
        """Print formatted health report to console"""
        report = self.get_startup_health_report()
        
        print("\n" + "="*60)
        print("ASSISTANT - SERVICE HEALTH REPORT")
        print("="*60)
        print(f"Startup Time: {report['startup_time_seconds']}s")
        print(f"Overall Health: {report['overall_health'].upper()}")
        print(f"Services: {report['services_status']['healthy']} healthy, "
              f"{report['services_status']['degraded']} degraded, "
              f"{report['services_status']['failed']} failed, "
              f"{report['services_status']['disabled']} disabled")
        
        if report['critical_failures'] > 0:
            print(f"\n⚠️  CRITICAL FAILURES: {report['critical_failures']}")
            
        print("\nService Details:")
        print("-" * 40)
        
        for name, info in report['services'].items():
            status_icon = {
                'healthy': '✅',
                'degraded': '⚠️',
                'failed': '❌',
                'disabled': '⭕',
                'initializing': '⏳'
            }.get(info['status'], '❓')
            
            critical_mark = ' 🔴' if info['critical'] else ' 🟡'
            print(f"{status_icon} {name}{critical_mark} - {info['status']}")
            if info['message']:
                print(f"    └─ {info['message']}")
            print(f"    └─ Started in {info['startup_time']}s")
        
        print("="*60)
        
        # Recommendations
        if report['overall_health'] == 'critical':
            print("\n🚨 SYSTEM REQUIRES ATTENTION")
            print("Critical services have failed. Check the errors above.")
        elif report['overall_health'] == 'degraded':
            print("\n⚠️  SYSTEM RUNNING WITH LIMITATIONS")
            print("Some services are degraded. Core functionality should work.")
        else:
            print("\n🎉 ALL SYSTEMS OPERATIONAL")
            
    def can_continue_startup(self) -> bool:
        """Determine if startup should continue despite failures"""
        # Allow startup if no critical services failed
        critical_failed = sum(1 for s in self.services.values() 
                            if s.status == 'failed' and s.critical)
        return critical_failed == 0

# Global health monitor instance
health_monitor = ServiceHealthMonitor()

def health_check_decorator(service_name: str, critical: bool = True):
    """Decorator for automatic health check registration"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            health_monitor.register_service(service_name, critical)
            try:
                result = func(*args, **kwargs)
                health_monitor.update_service_status(service_name, 'healthy', 'Service started successfully')
                return result
            except Exception as e:
                health_monitor.update_service_status(service_name, 'failed', str(e))
                if critical:
                    print(f"[CRITICAL] Service {service_name} failed: {e}")
                    raise
                else:
                    print(f"[NON-CRITICAL] Service {service_name} failed: {e}")
                    return None
        return wrapper
    return decorator
