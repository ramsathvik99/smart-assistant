import sys

def apply_patches():
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
    del_upd_end_marker = "                        else:\n                            result[\"status\"] = \"error\"\n                            result[\"response\"] = \"Reminder action not implemented yet.\""

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

    with open(router_path, "w", encoding="utf-8") as f:
        f.write(router_code)
    print("Successfully patched core/unified_command_router.py")

if __name__ == "__main__":
    apply_patches()

