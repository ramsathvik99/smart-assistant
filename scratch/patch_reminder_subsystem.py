import sys

def apply_patches():
    # 1. Patch extensions/reminder_engine/reminder_scheduler.py
    sched_path = "extensions/reminder_engine/reminder_scheduler.py"
    with open(sched_path, "r", encoding="utf-8") as f:
        sched_code = f.read().replace("\r\n", "\n")

    # In add_reminder, ensure state: "SCHEDULED" is set
    sched_target_1 = """                if existing:
                    existing["text"] = text
                    existing["trigger_time"] = exact_trigger_time
                    existing["target_time"] = target_time
                    existing["delay_seconds"] = calculated_delay
                    existing["user_id"] = eff_user_id
                    existing["triggered"] = False
                    existing["is_db_backed"] = persisted"""

    sched_repl_1 = """                if existing:
                    existing["text"] = text
                    existing["trigger_time"] = exact_trigger_time
                    existing["target_time"] = target_time
                    existing["delay_seconds"] = calculated_delay
                    existing["user_id"] = eff_user_id
                    existing["triggered"] = False
                    existing["state"] = "SCHEDULED"
                    existing["is_db_backed"] = persisted"""

    sched_target_2 = """                self.reminders.append({
                    "id": reminder_id,
                    "text": text,
                    "trigger_time": exact_trigger_time,
                    "target_time": target_time,
                    "delay_seconds": calculated_delay,
                    "triggered": False,
                    "created_at": time.time(),
                    "user_id": eff_user_id,
                    "recurrence": recurrence,
                    "is_db_backed": persisted
                })"""

    sched_repl_2 = """                self.reminders.append({
                    "id": reminder_id,
                    "text": text,
                    "trigger_time": exact_trigger_time,
                    "target_time": target_time,
                    "delay_seconds": calculated_delay,
                    "triggered": False,
                    "state": "SCHEDULED",
                    "created_at": time.time(),
                    "user_id": eff_user_id,
                    "recurrence": recurrence,
                    "is_db_backed": persisted
                })"""

    assert sched_target_1 in sched_code, "sched_target_1 not found"
    assert sched_target_2 in sched_code, "sched_target_2 not found"
    sched_code = sched_code.replace(sched_target_1, sched_repl_1, 1)
    sched_code = sched_code.replace(sched_target_2, sched_repl_2, 1)

    # Replace cancel_reminder through end of edit_reminder
    start_marker = "    def cancel_reminder(self, reminder_id: str, user_id: Optional[int] = None) -> bool:"
    end_marker = "    def get_pending_reminders(self) -> List[Dict]:"

    start_idx = sched_code.find(start_marker)
    end_idx = sched_code.find(end_marker)
    assert start_idx != -1 and end_idx != -1, f"Markers not found: start={start_idx}, end={end_idx}"

    new_methods_code = """    def cancel_reminder(self, reminder_id: str, user_id: Optional[int] = None) -> bool:
        \"\"\"
        Cancel a pending reminder.
        Validates ownership against the reminder's owner_id.
        If database-backed, deletes from database.
        Synchronizes in-memory scheduler state atomically via state transitions without holding global lock across DB I/O.
        \"\"\"
        target_id_str = str(reminder_id)
        eff_user_id = user_id if user_id is not None else self.user_id

        # 1. Inspect memory under lock for existence, ownership validation, and atomic state transition
        with self._lock:
            existing = next((r for r in self.reminders if str(r.get("id")) == target_id_str), None)
            if not existing:
                # Fallback: check if row exists directly in database if db_manager is present
                if self.db_manager and eff_user_id is not None:
                    try:
                        db_deleted = self.db_manager.delete_reminder(eff_user_id, target_id_str)
                        return bool(db_deleted)
                    except Exception as e:
                        print(f"[REMINDER ENGINE] Database delete error during cancel_reminder fallback: {e}")
                        return False
                return False
            
            owner_id = existing.get("user_id")
            # Enforce ownership: Caller must be authenticated if reminder has an owner
            if eff_user_id is None and owner_id is not None:
                print(f"[REMINDER ENGINE] Unauthorized cancellation: No authenticated user provided for reminder {target_id_str}")
                return False
            # Caller cannot cancel another user's reminder
            if eff_user_id is not None and owner_id is not None and eff_user_id != owner_id:
                print(f"[REMINDER ENGINE] Unauthorized cancellation: User {eff_user_id} cannot cancel reminder {target_id_str} owned by User {owner_id}")
                return False
            
            # Atomic state guard
            curr_state = existing.get("state", "SCHEDULED")
            if curr_state in ("CANCELLING", "TRIGGERING", "TRIGGERED", "RESCHEDULING", "EDITING"):
                print(f"[REMINDER ENGINE] Cannot cancel reminder {target_id_str}: in state {curr_state}")
                return False
            if existing.get("triggered", False):
                print(f"[REMINDER ENGINE] Cannot cancel reminder {target_id_str}: already triggered")
                return False
            
            # Transition to CANCELLING under lock
            existing["state"] = "CANCELLING"
            is_db_backed = bool(existing.get("is_db_backed", False))
            target_owner = owner_id if owner_id is not None else eff_user_id

        # 2. Database cancellation outside lock (avoiding deadlocks)
        if is_db_backed:
            if not self.db_manager or target_owner is None:
                print(f"[REMINDER ENGINE] Cannot delete DB-backed reminder {target_id_str}: Database unavailable")
                with self._lock:
                    if existing in self.reminders and existing.get("state") == "CANCELLING":
                        existing["state"] = "SCHEDULED"
                return False
            try:
                db_deleted = self.db_manager.delete_reminder(target_owner, target_id_str)
                if not db_deleted:
                    print(f"[REMINDER ENGINE] Database deletion failed for reminder {target_id_str}")
                    with self._lock:
                        if existing in self.reminders and existing.get("state") == "CANCELLING":
                            existing["state"] = "SCHEDULED"
                    return False
            except Exception as e:
                print(f"[REMINDER ENGINE] Database delete error during cancel_reminder: {e}")
                with self._lock:
                    if existing in self.reminders and existing.get("state") == "CANCELLING":
                        existing["state"] = "SCHEDULED"
                return False

        # 3. Synchronize in-memory scheduler state
        with self._lock:
            if existing in self.reminders:
                self.reminders.remove(existing)
                print(f"[REMINDER ENGINE] Cancelled reminder: {target_id_str}")
                return True
            return False

    def reschedule_reminder(
        self,
        reminder_id: str,
        new_target_time: datetime.datetime,
        new_text: Optional[str] = None,
        user_id: Optional[int] = None
    ) -> bool:
        \"\"\"
        Reschedule a reminder to a new target time.
        Updates both database (if database-backed) and the active scheduler job.
        Ensures the reminder will not fire at the old time.
        \"\"\"
        target_id_str = str(reminder_id)
        eff_user_id = user_id if user_id is not None else self.user_id

        # 1. Inspect memory under lock for existence, ownership validation, and atomic state transition
        with self._lock:
            existing = next((r for r in self.reminders if str(r.get("id")) == target_id_str), None)
            if not existing:
                # Fallback: check database if DB-backed and user_id provided
                if self.db_manager and eff_user_id is not None:
                    try:
                        rem = self.db_manager.get_reminder_by_id(eff_user_id, target_id_str)
                        if rem:
                            new_time_str = new_target_time.strftime("%Y-%m-%d %H:%M:%S")
                            db_updated = self.db_manager.update_reminder(eff_user_id, target_id_str, task_text=new_text, due_at=new_time_str)
                            if db_updated:
                                now = datetime.datetime.now()
                                if new_target_time > now:
                                    self.add_reminder_at_time(
                                        new_text or rem.get("task_text", ""),
                                        new_target_time,
                                        reminder_id=target_id_str,
                                        user_id=eff_user_id,
                                        is_db_backed=True
                                    )
                                return True
                    except Exception as e:
                        print(f"[REMINDER ENGINE] DB fallback error during reschedule: {e}")
                return False
            
            owner_id = existing.get("user_id")
            if eff_user_id is None and owner_id is not None:
                print(f"[REMINDER ENGINE] Unauthorized reschedule: No authenticated user provided for reminder {target_id_str}")
                return False
            if eff_user_id is not None and owner_id is not None and eff_user_id != owner_id:
                print(f"[REMINDER ENGINE] Unauthorized reschedule: User {eff_user_id} cannot reschedule reminder {target_id_str} owned by User {owner_id}")
                return False
            
            curr_state = existing.get("state", "SCHEDULED")
            if curr_state in ("CANCELLING", "TRIGGERING", "TRIGGERED", "RESCHEDULING", "EDITING"):
                print(f"[REMINDER ENGINE] Cannot reschedule reminder {target_id_str}: in state {curr_state}")
                return False
            if existing.get("triggered", False):
                print(f"[REMINDER ENGINE] Cannot reschedule reminder {target_id_str}: already triggered")
                return False
            
            existing["state"] = "RESCHEDULING"
            is_db_backed = bool(existing.get("is_db_backed", False))
            target_owner = owner_id if owner_id is not None else eff_user_id

        # 2. Database update outside lock (avoiding deadlocks)
        if is_db_backed:
            if not self.db_manager or target_owner is None:
                print(f"[REMINDER ENGINE] Cannot reschedule DB-backed reminder {target_id_str}: Database unavailable")
                with self._lock:
                    if existing in self.reminders and existing.get("state") == "RESCHEDULING":
                        existing["state"] = "SCHEDULED"
                return False
            try:
                new_time_str = new_target_time.strftime("%Y-%m-%d %H:%M:%S")
                db_updated = self.db_manager.update_reminder(target_owner, target_id_str, task_text=new_text, due_at=new_time_str)
                if not db_updated:
                    print(f"[REMINDER ENGINE] Database update returned false for reminder {target_id_str}")
                    with self._lock:
                        if existing in self.reminders and existing.get("state") == "RESCHEDULING":
                            existing["state"] = "SCHEDULED"
                    return False
            except Exception as e:
                print(f"[REMINDER ENGINE] Database reschedule error: {e}")
                with self._lock:
                    if existing in self.reminders and existing.get("state") == "RESCHEDULING":
                        existing["state"] = "SCHEDULED"
                return False

        # 3. Synchronize in-memory scheduler state
        now = datetime.datetime.now()
        exact_trigger_time = new_target_time.timestamp()
        delay_seconds = max(0.0, (new_target_time - now).total_seconds())

        with self._lock:
            if existing in self.reminders:
                if new_text:
                    existing["text"] = new_text
                existing["trigger_time"] = exact_trigger_time
                existing["target_time"] = new_target_time
                existing["delay_seconds"] = delay_seconds
                existing["triggered"] = False
                existing["state"] = "SCHEDULED"
                print(f"[REMINDER ENGINE] Rescheduled existing reminder {target_id_str} to {new_target_time.strftime('%Y-%m-%d %H:%M:%S')}")
                return True
            return False

    def edit_reminder(
        self,
        reminder_id: str,
        new_text: Optional[str] = None,
        new_target_time: Optional[datetime.datetime] = None,
        user_id: Optional[int] = None
    ) -> bool:
        \"\"\"Edit text and/or target time for a reminder.\"\"\"
        if new_target_time:
            return self.reschedule_reminder(reminder_id, new_target_time, new_text=new_text, user_id=user_id)
        
        target_id_str = str(reminder_id)
        eff_user_id = user_id if user_id is not None else self.user_id

        with self._lock:
            existing = next((r for r in self.reminders if str(r.get("id")) == target_id_str), None)
            if not existing:
                if self.db_manager and eff_user_id is not None and new_text:
                    try:
                        db_ok = self.db_manager.update_reminder(eff_user_id, target_id_str, task_text=new_text)
                        return bool(db_ok)
                    except Exception as e:
                        print(f"[REMINDER ENGINE] DB fallback error during edit: {e}")
                return False
            
            owner_id = existing.get("user_id")
            if eff_user_id is None and owner_id is not None:
                return False
            if eff_user_id is not None and owner_id is not None and eff_user_id != owner_id:
                return False
            
            curr_state = existing.get("state", "SCHEDULED")
            if curr_state in ("CANCELLING", "TRIGGERING", "TRIGGERED", "RESCHEDULING", "EDITING"):
                return False
            if existing.get("triggered", False):
                return False
            
            existing["state"] = "EDITING"
            is_db_backed = bool(existing.get("is_db_backed", False))
            target_owner = owner_id if owner_id is not None else eff_user_id

        if is_db_backed and self.db_manager and target_owner is not None and new_text:
            try:
                db_ok = self.db_manager.update_reminder(target_owner, target_id_str, task_text=new_text)
                if not db_ok:
                    with self._lock:
                        if existing in self.reminders and existing.get("state") == "EDITING":
                            existing["state"] = "SCHEDULED"
                    return False
            except Exception as e:
                print(f"[REMINDER ENGINE] Database edit error: {e}")
                with self._lock:
                    if existing in self.reminders and existing.get("state") == "EDITING":
                        existing["state"] = "SCHEDULED"
                return False

        with self._lock:
            if existing in self.reminders:
                if new_text:
                    existing["text"] = new_text
                existing["state"] = "SCHEDULED"
                return True
        return False

"""

    sched_code = sched_code[:start_idx] + new_methods_code + sched_code[end_idx:]

    # In get_pending_reminders:
    old_pending = """    def get_pending_reminders(self) -> List[Dict]:
        \"\"\"Get list of pending (not triggered) reminders.\"\"\"
        with self._lock:
            return [r for r in self.reminders if not r["triggered"]]"""

    new_pending = """    def get_pending_reminders(self) -> List[Dict]:
        \"\"\"Get list of pending (not triggered) reminders.\"\"\"
        with self._lock:
            return [r for r in self.reminders if not r["triggered"] and r.get("state", "SCHEDULED") == "SCHEDULED"]"""

    assert old_pending in sched_code, "old_pending not found"
    sched_code = sched_code.replace(old_pending, new_pending, 1)

    # In _run_scheduler:
    old_run = """                # Find reminders that need to trigger
                with self._lock:
                    for reminder in self.reminders:
                        if not reminder["triggered"] and now >= reminder["trigger_time"]:
                            reminders_to_trigger.append(reminder)
                            reminder["triggered"] = True"""

    new_run = """                # Find reminders that need to trigger
                with self._lock:
                    for reminder in self.reminders:
                        if not reminder.get("triggered") and reminder.get("state", "SCHEDULED") == "SCHEDULED" and now >= reminder["trigger_time"]:
                            reminders_to_trigger.append(reminder)
                            reminder["state"] = "TRIGGERING"
                            reminder["triggered"] = True"""

    assert old_run in sched_code, "old_run not found"
    sched_code = sched_code.replace(old_run, new_run, 1)

    # In _trigger_reminder:
    old_trig_top = """        with self._lock:
            if reminder.get("_in_trigger"):
                return
            reminder["_in_trigger"] = True
            reminder["triggered"] = True"""

    new_trig_top = """        with self._lock:
            if reminder.get("_in_trigger"):
                return
            reminder["_in_trigger"] = True
            reminder["triggered"] = True
            reminder["state"] = "TRIGGERING" """

    assert old_trig_top in sched_code, "old_trig_top not found"
    sched_code = sched_code.replace(old_trig_top, new_trig_top, 1)

    old_trig_rec = """                with self._lock:
                    reminder["trigger_time"] = next_time.timestamp()
                    reminder["target_time"] = next_time
                    reminder["triggered"] = False
                    reminder["delay_seconds"] = max(0.0, (next_time - datetime.datetime.now()).total_seconds())"""

    new_trig_rec = """                with self._lock:
                    reminder["trigger_time"] = next_time.timestamp()
                    reminder["target_time"] = next_time
                    reminder["triggered"] = False
                    reminder["state"] = "SCHEDULED"
                    reminder["delay_seconds"] = max(0.0, (next_time - datetime.datetime.now()).total_seconds())"""

    assert old_trig_rec in sched_code, "old_trig_rec not found"
    sched_code = sched_code.replace(old_trig_rec, new_trig_rec, 1)

    old_trig_fin = """        finally:
            with self._lock:
                reminder["_in_trigger"] = False"""

    new_trig_fin = """        finally:
            with self._lock:
                reminder["_in_trigger"] = False
                if reminder.get("state") == "TRIGGERING":
                    reminder["state"] = "TRIGGERED" """

    assert old_trig_fin in sched_code, "old_trig_fin not found"
    sched_code = sched_code.replace(old_trig_fin, new_trig_fin, 1)

    # In clear_completed_reminders:
    old_clear_comp = """    def clear_completed_reminders(self):
        \"\"\"Remove all completed reminders from memory.\"\"\"
        with self._lock:
            before_count = len(self.reminders)
            self.reminders = [r for r in self.reminders if not r["triggered"]]"""

    new_clear_comp = """    def clear_completed_reminders(self):
        \"\"\"Remove all completed reminders from memory.\"\"\"
        with self._lock:
            before_count = len(self.reminders)
            self.reminders = [r for r in self.reminders if not r["triggered"] and r.get("state", "SCHEDULED") != "TRIGGERED"]"""

    assert old_clear_comp in sched_code, "old_clear_comp not found"
    sched_code = sched_code.replace(old_clear_comp, new_clear_comp, 1)

    with open(sched_path, "w", encoding="utf-8") as f:
        f.write(sched_code)
    print("Successfully patched extensions/reminder_engine/reminder_scheduler.py")

    # 2. Patch core/unified_command_router.py
    router_path = "core/unified_command_router.py"
    with open(router_path, "r", encoding="utf-8") as f:
        router_code = f.read().replace("\r\n", "\n")

    # Scheduler initialization with user_id & db_manager
    old_init_sched = """                    # Ensure scheduler is initialized
                    scheduler = get_scheduler()
                    if scheduler is None:
                        scheduler = initialize_scheduler()"""

    new_init_sched = """                    # Ensure scheduler is initialized with current db_manager and user_id
                    scheduler = get_scheduler()
                    if scheduler is None:
                        scheduler = initialize_scheduler(db_manager=db_manager, user_id=user_id)
                    else:
                        if scheduler.db_manager is None:
                            scheduler.db_manager = db_manager
                        if user_id is not None and scheduler.user_id != user_id:
                            scheduler.reload_for_user(user_id)"""

    assert old_init_sched in router_code, "old_init_sched not found"
    router_code = router_code.replace(old_init_sched, new_init_sched, 1)

    # In CREATE action, pass is_db_backed=True
    old_create_sched = """scheduler.add_reminder_at_time(parse_result["task_text"], due_datetime, str(reminder_id), user_id, recurrence=parse_result.get("recurrence"))"""
    new_create_sched = """scheduler.add_reminder_at_time(parse_result["task_text"], due_datetime, str(reminder_id), user_id, recurrence=parse_result.get("recurrence"), is_db_backed=True)"""
    assert old_create_sched in router_code, "old_create_sched not found"
    router_code = router_code.replace(old_create_sched, new_create_sched, 1)

    # In DELETE and UPDATE action, delegate to scheduler directly (eliminating double deletion and passing user_id)
    del_upd_start_marker = "                        elif action in (ReminderAction.DELETE, ReminderAction.DELETE.value) or action_val == \"DELETE\":"
    del_upd_end_marker = "                        else:\n                            result[\"status\"] = \"error\""

    du_start_idx = router_code.find(del_upd_start_marker)
    du_end_idx = router_code.find(del_upd_end_marker)
    assert du_start_idx != -1 and du_end_idx != -1, f"du markers not found: start={du_start_idx}, end={du_end_idx}"

    new_del_and_upd = """                        elif action in (ReminderAction.DELETE, ReminderAction.DELETE.value) or action_val == "DELETE":
                            # Authoritative single operation: router delegates directly to scheduler
                            reminder_id = parse_result["reminder_id"]
                            success = scheduler.cancel_reminder(str(reminder_id), user_id=user_id)
                            
                            if success:
                                result["status"] = "success"
                                result["response"] = "Reminder deleted."
                            else:
                                result["status"] = "error"
                                result["response"] = "Failed to delete reminder."
                        
                        elif action in (ReminderAction.UPDATE, ReminderAction.UPDATE.value) or action_val == "UPDATE":
                            # Authoritative single operation: router delegates directly to scheduler
                            reminder_id = parse_result["reminder_id"]
                            new_time_str = parse_result.get("new_due_at")
                            new_text = parse_result.get("new_task_text")
                            
                            if new_time_str:
                                try:
                                    try:
                                        new_due_dt = datetime.strptime(new_time_str, "%Y-%m-%d %H:%M:%S")
                                    except ValueError:
                                        new_due_dt = datetime.fromisoformat(new_time_str)
                                    success = scheduler.reschedule_reminder(
                                        str(reminder_id),
                                        new_due_dt,
                                        new_text=new_text,
                                        user_id=user_id
                                    )
                                except Exception as parse_err:
                                    self.logger.error(f"Error parsing update time {new_time_str}: {parse_err}")
                                    success = False
                            else:
                                success = scheduler.edit_reminder(
                                    str(reminder_id),
                                    new_text=new_text,
                                    user_id=user_id
                                )
                            
                            if success:
                                result["status"] = "success"
                                result["response"] = "Reminder updated."
                            else:
                                result["status"] = "error"
                                result["response"] = "Failed to update reminder."
                        """

    router_code = router_code[:du_start_idx] + new_del_and_upd + router_code[du_end_idx:]

    # In _execute_schedule_clear: ensure scheduler.cancel_reminder is called if available
    old_clear = """                db = self._schedule_db_manager()
                for rem in self._collect_active_reminders(user_id):
                    outcome["attempted"]["reminders"] += 1
                    rid = rem.get("id")
                    if rid is None:
                        continue
                    try:
                        if db.delete_reminder(int(user_id), rid):
                            outcome["deleted"]["reminders"] += 1
                    except Exception as e:
                        outcome["errors"].append(f"reminder:{type(e).__name__}")"""

    new_clear = """                db = self._schedule_db_manager()
                sched = get_scheduler()
                for rem in self._collect_active_reminders(user_id):
                    outcome["attempted"]["reminders"] += 1
                    rid = rem.get("id")
                    if rid is None:
                        continue
                    try:
                        if sched and sched.cancel_reminder(str(rid), user_id=int(user_id)):
                            outcome["deleted"]["reminders"] += 1
                        elif db and db.delete_reminder(int(user_id), rid):
                            outcome["deleted"]["reminders"] += 1
                    except Exception as e:
                        outcome["errors"].append(f"reminder:{type(e).__name__}")"""

    assert old_clear in router_code, "old_clear not found"
    router_code = router_code.replace(old_clear, new_clear, 1)

    with open(router_path, "w", encoding="utf-8") as f:
        f.write(router_code)
    print("Successfully patched core/unified_command_router.py")

if __name__ == "__main__":
    apply_patches()
