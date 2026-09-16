"""
System Awareness Module
Monitors system state and provides intelligent suggestions.
"""

import logging
import psutil
import time
from typing import Dict, Optional, List
from dataclasses import dataclass

@dataclass
class SystemState:
    """Represents current system state"""
    cpu_percent: float
    memory_percent: float
    battery_percent: Optional[float]
    battery_plugged: bool
    disk_usage: float
    network_active: bool
    uptime: float

class SystemAwareness:
    """Monitors system state and provides intelligent suggestions"""
    
    def __init__(self, logger: logging.Logger | None = None):
        self.logger = logger or logging.getLogger("assistant.intelligence.system")
        
        # Thresholds for alerts
        self.thresholds = {
            "cpu_high": 90.0,
            "cpu_warning": 75.0,
            "memory_high": 85.0,
            "memory_warning": 70.0,
            "battery_low": 20.0,
            "battery_warning": 30.0,
            "disk_high": 90.0,
            "disk_warning": 80.0
        }
        
        # Last check time to avoid frequent polling
        self.last_check_time = 0
        self.check_interval = 30  # Check every 30 seconds
        
        # Cached system state
        self._cached_state: Optional[SystemState] = None
    
    def get_system_state(self, force_refresh: bool = False) -> SystemState:
        """Get current system state with caching."""
        current_time = time.time()
        
        if (not force_refresh and 
            self._cached_state and 
            current_time - self.last_check_time < self.check_interval):
            return self._cached_state
        
        try:
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            
            # Memory usage
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            
            # Battery information
            battery_percent = None
            battery_plugged = False
            try:
                battery = psutil.sensors_battery()
                if battery:
                    battery_percent = battery.percent
                    battery_plugged = battery.power_plugged
            except (AttributeError, NotImplementedError):
                pass
            
            # Disk usage
            disk = psutil.disk_usage('/')
            disk_usage = (disk.used / disk.total) * 100
            
            # Network activity
            network_active = False
            try:
                network = psutil.net_io_counters()
                network_active = (network.bytes_sent + network.bytes_recv) > 0
            except (AttributeError, NotImplementedError):
                pass
            
            # System uptime
            uptime = time.time() - psutil.boot_time()
            
            self._cached_state = SystemState(
                cpu_percent=cpu_percent,
                memory_percent=memory_percent,
                battery_percent=battery_percent,
                battery_plugged=battery_plugged,
                disk_usage=disk_usage,
                network_active=network_active,
                uptime=uptime
            )
            
            self.last_check_time = current_time
            
        except Exception as e:
            self.logger.error(f"Error getting system state: {e}")
            # Return cached state or default
            if self._cached_state:
                return self._cached_state
            
            return SystemState(
                cpu_percent=0.0,
                memory_percent=0.0,
                battery_percent=None,
                battery_plugged=False,
                disk_usage=0.0,
                network_active=False,
                uptime=0.0
            )
        
        return self._cached_state
    
    def get_system_suggestions(self) -> List[str]:
        """Get intelligent suggestions based on system state."""
        state = self.get_system_state()
        suggestions = []
        
        # Battery suggestions
        if state.battery_percent is not None:
            if state.battery_percent < self.thresholds["battery_low"] and not state.battery_plugged:
                suggestions.append("Battery is critically low. You may want to plug in soon.")
            elif state.battery_percent < self.thresholds["battery_warning"] and not state.battery_plugged:
                suggestions.append("Battery is getting low. Consider plugging in.")
            elif state.battery_percent < self.thresholds["battery_low"] and state.battery_plugged:
                suggestions.append("Battery is charging but still low.")
        
        # CPU suggestions
        if state.cpu_percent > self.thresholds["cpu_high"]:
            suggestions.append("System is under heavy CPU load. You may want to close some applications.")
        elif state.cpu_percent > self.thresholds["cpu_warning"]:
            suggestions.append("CPU usage is elevated. Monitor performance.")
        
        # Memory suggestions
        if state.memory_percent > self.thresholds["memory_high"]:
            suggestions.append("Memory usage is high. Consider closing unused applications.")
        elif state.memory_percent > self.thresholds["memory_warning"]:
            suggestions.append("Memory usage is getting high.")
        
        # Disk suggestions
        if state.disk_usage > self.thresholds["disk_high"]:
            suggestions.append("Disk space is critically low. Free up some space.")
        elif state.disk_usage > self.thresholds["disk_warning"]:
            suggestions.append("Disk space is getting low.")
        
        # Uptime-based suggestions
        uptime_hours = state.uptime / 3600
        if uptime_hours > 8:
            suggestions.append("System has been running for a while. Consider taking a break.")
        
        return suggestions
    
    def should_interrupt_for_alert(self) -> bool:
        """Determine if system state requires immediate attention."""
        state = self.get_system_state()
        
        # Critical conditions that need immediate attention
        if (state.battery_percent is not None and 
            state.battery_percent < self.thresholds["battery_low"] and 
            not state.battery_plugged):
            return True
        
        if state.cpu_percent > self.thresholds["cpu_high"]:
            return True
        
        if state.memory_percent > self.thresholds["memory_high"]:
            return True
        
        return False
    
    def get_performance_summary(self) -> Dict[str, str]:
        """Get a human-readable performance summary."""
        state = self.get_system_state()
        
        def get_status(value: float, warning_threshold: float, high_threshold: float) -> str:
            if value >= high_threshold:
                return "High"
            elif value >= warning_threshold:
                return "Moderate"
            else:
                return "Good"
        
        summary = {
            "cpu": f"{state.cpu_percent:.1f}% ({get_status(state.cpu_percent, self.thresholds['cpu_warning'], self.thresholds['cpu_high'])})",
            "memory": f"{state.memory_percent:.1f}% ({get_status(state.memory_percent, self.thresholds['memory_warning'], self.thresholds['memory_high'])})",
            "disk": f"{state.disk_usage:.1f}% ({get_status(state.disk_usage, self.thresholds['disk_warning'], self.thresholds['disk_high'])})"
        }
        
        if state.battery_percent is not None:
            battery_status = "Charging" if state.battery_plugged else "On Battery"
            summary["battery"] = f"{state.battery_percent:.1f}% ({battery_status})"
        
        return summary
    
    def is_system_stable(self) -> bool:
        """Check if system is in a stable state for intensive tasks."""
        state = self.get_system_state()
        
        # System is stable if:
        # - CPU < 80%
        # - Memory < 80%
        # - Battery > 20% (if on battery)
        # - Disk < 90%
        
        if state.cpu_percent > 80:
            return False
        
        if state.memory_percent > 80:
            return False
        
        if (state.battery_percent is not None and 
            not state.battery_plugged and 
            state.battery_percent < 20):
            return False
        
        if state.disk_usage > 90:
            return False
        
        return True
    
    def get_optimization_suggestions(self) -> List[str]:
        """Get suggestions for system optimization."""
        state = self.get_system_state()
        suggestions = []
        
        # CPU optimization
        if state.cpu_percent > 75:
            suggestions.append("Close unnecessary browser tabs and applications")
            suggestions.append("Check for background processes using high CPU")
        
        # Memory optimization
        if state.memory_percent > 70:
            suggestions.append("Clear browser cache and temporary files")
            suggestions.append("Restart memory-intensive applications")
        
        # Battery optimization
        if state.battery_percent is not None and not state.battery_plugged:
            if state.battery_percent < 50:
                suggestions.append("Enable battery saver mode")
                suggestions.append("Reduce screen brightness")
                suggestions.append("Close background applications")
        
        # General optimization
        if state.uptime > 24 * 3600:  # More than 24 hours
            suggestions.append("Consider restarting your system")
        
        return suggestions

# Global system awareness instance
_system_awareness = None

def get_system_awareness() -> SystemAwareness:
    """Get the global system awareness instance."""
    global _system_awareness
    if _system_awareness is None:
        _system_awareness = SystemAwareness()
    return _system_awareness

def reset_system_awareness():
    """Reset the global system awareness instance (for testing)."""
    global _system_awareness
    _system_awareness = None
