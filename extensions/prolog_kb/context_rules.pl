% ============================================
% CENTRAL REASONING ENGINE - CONTEXT RULES
% ============================================

% Basic Context Suggestions
suggest(reopen_last_app) :- last_app(Name), context(system, _).
suggest(open_browser) :- last_browser(Name), context(system, _).
suggest(stay_in_context) :- context(app, _).
suggest(use_web_context) :- context(browser, _).

% Enhanced Context Reasoning (Advanced AI-style)
can_go_back :- context(browser, _).
can_go_back :- context(app, _).
can_navigate_back :- context(browser, _), intent(navigation).
can_navigate_back :- context(app, _), intent(navigation).

% Context-Aware Actions
context_action(browser_back) :- context(browser, _), intent(navigation).
context_action(app_switch) :- context(app, _), intent(system_open).
context_action(tab_close) :- context(browser, _), token(close).
context_action(window_close) :- context(app, _), token(close).

% Context State Management
active_context(browser) :- context(browser, _).
active_context(system) :- context(system, _).
active_context(app) :- context(app, _).
active_context(none) :- \+ context(_, _).

% Advanced AI Intelligence - Context Awareness
can_go_back :- active_context(browser).
can_go_back :- active_context(app).
should_use_browser :- token(youtube); token(chrome); token(search).
should_use_system :- token(open), \+ token(youtube); token(close).
should_play_music :- token(play), (token(music); token(song); token(audio)).

% Advanced AI Suggestions / Intelligence
suggest("You should drink water") :- long_idle_time.
suggest("Would you like me to search the web?") :- token(find), \+ token(search).
suggest("I can help you navigate back") :- intent(navigation), \+ can_go_back.
suggest("Let me open that in your browser") :- token(youtube), \+ active_context(browser).
suggest("I can play some music for you") :- token(music), \+ should_play_music.

% Context Transitions
valid_transition(system, browser) :- intent(browser).
valid_transition(system, app) :- intent(system_open).
valid_transition(browser, system) :- intent(system_open).
valid_transition(app, system) :- intent(system_open).

% Memory Integration
remember_last_command(Command) :- utterance(Command), \+ Command = "".
can_repeat_command :- remember_last_command(_).
get_last_command :- remember_last_command(Command).

% Context Transitions
valid_transition(system, browser) :- intent(browser).
valid_transition(system, app) :- intent(system_open).
valid_transition(browser, system) :- intent(system_open).
valid_transition(app, system) :- intent(system_open).
valid_transition(browser, browser) :- intent(search).
valid_transition(app, app) :- intent(system_open).

% Context History Tracking
last_context(system) :- last_app(_).
last_context(browser) :- last_browser(_).
last_context(app) :- last_app(_), \+ last_browser(_).

% Context-Intent Compatibility
compatible_context(browser, intent(search)).
compatible_context(browser, intent(navigation)).
compatible_context(system, intent(system_open)).
compatible_context(system, intent(system_close)).
compatible_context(app, intent(system_close)).
compatible_context(none, _).

% Context-Based Decision Enhancement
enhance_decision(open_browser) :- active_context(system), intent(browser).
enhance_decision(navigate_back) :- active_context(browser), intent(navigation).
enhance_decision(close_current) :- active_context(app), intent(system_close).
enhance_decision(switch_context) :- active_context(browser), intent(system_open).

% Context Error Detection
context_error(no_context_for_navigation) :- intent(navigation), \+ can_go_back.
context_error(invalid_context_transition) :- context(From, _), intent(open), \+ valid_transition(From, _).
context_error(context_mismatch) :- context(Context, _), \+ compatible_context(Context, _).

% Context Recovery Suggestions
context_recovery(switch_to_browser) :- intent(browser), \+ active_context(browser).
context_recovery(switch_to_system) :- intent(system_open), \+ active_context(system).
context_recovery(specify_context) :- context_error(_).
context_recovery(use_last_context) :- last_context(Last), \+ active_context(Last).

% Context Optimization
optimize_context(browser_focus) :- context(browser, _), intent(search).
optimize_context(app_focus) :- context(app, _), intent(system_control).
optimize_context(system_ready) :- active_context(none).

% Context Learning
learned_context_preference(browser, youtube) :- token(open), token(youtube), context(browser, youtube).
learned_context_preference(system, notepad) :- token(open), token(notepad), context(system, notepad).
learned_context_navigation_pattern(back_usage) :- intent(navigation), can_go_back.

% Context State Persistence
persistent_context(browser) :- context(browser, _), \+ intent(close).
persistent_context(app) :- context(app, _), \+ intent(close).
temporary_context(system) :- context(system, _).

% Context-Aware Priority
context_priority(high) :- context(browser, _), intent(reminder).
context_priority(medium) :- context(app, _), intent(reminder).
context_priority(low) :- context(none, _), intent(query).

% Context Integration with Other Modules
integrate_context(reminder) :- context(_, _), intent(reminder).
integrate_context(music) :- context(browser, _), intent(music).
integrate_context(search) :- context(browser, _), intent(search).

% Context Cleanup and Maintenance
cleanup_context( stale ) :- context(_, _), \+ utterance(_).
cleanup_context(inactive) :- context(_, _), \+ recent_activity.
maintain_context(active) :- context(_, _), recent_activity.

