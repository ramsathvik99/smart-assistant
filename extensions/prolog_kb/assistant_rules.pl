% ============================================
% CENTRAL REASONING ENGINE - ASSISTANT RULES
% ============================================

% Basic Assistant Rules
suggest(confirm_destructive) :- awaiting_confirmation(yes).
decide_action(use_last_app) :- context(app, _).
decide_action(use_last_browser) :- context(browser, _).

% Enhanced Task Priority Rules
task_priority(Text, high) :- token(urgent), utterance(Text).
task_priority(Text, high) :- token(emergency), utterance(Text).
task_priority(Text, high) :- token(critical), utterance(Text).
task_priority(Text, medium) :- token(today), utterance(Text).
task_priority(Text, medium) :- token(important), utterance(Text).
task_priority(Text, medium) :- token(soon), utterance(Text).
task_priority(Text, low) :- token(later), utterance(Text).
task_priority(Text, low) :- token(sometime), utterance(Text).
task_priority(Text, low) :- token(when), token(free), utterance(Text).

% Reminder Enhancement Rules
should_remind(Text, soon) :- token(remind), utterance(Text).
should_remind(Text, now) :- token(remind), token(immediately), utterance(Text).
should_remind(Text, later) :- token(remind), token(later), utterance(Text).
reminder_priority(Text, high) :- token(remind), token(important), utterance(Text).
reminder_priority(Text, medium) :- token(remind), utterance(Text), \+ reminder_priority(Text, high).
reminder_priority(Text, low) :- token(remind), token(casual), utterance(Text).

% Assistant Behavior Rules
assistant_response(greeting) :- token(hello).
assistant_response(greeting) :- token(hi).
assistant_response(greeting) :- token(hey).
assistant_response(farewell) :- token(bye).
assistant_response(farewell) :- token(goodbye).
assistant_response(acknowledgment) :- token(thanks).
assistant_response(acknowledgment) :- token(thank).
assistant_response(confirmation) :- token(yes).
assistant_response(confirmation) :- token(ok).
assistant_response(negation) :- token(no).
assistant_response(negation) :- token(nope).

% Command Processing Rules
process_command(quick) :- quick_decision(_).
process_command(standard) :- decide_action(_), \+ quick_decision(_).
process_command(complex) :- plan(_), \+ decide_action(_).
process_command(error_recovery) :- detect_error(_).

% User Intent Analysis
user_intent(help) :- token(help), token(please).
user_intent(clarification) :- token(what), token(do), token(you), token(mean).
user_intent(correction) :- token(no), token( thats), token(not), token(right).
user_intent(expansion) :- token(tell), token(me), token(more).
user_intent(repetition) :- token(again), token(repeat).

% Assistant State Management
assistant_state(ready) :- \+ context(_, _).
assistant_state(busy) :- context(_, _), \+ awaiting_confirmation(_).
assistant_state(waiting) :- awaiting_confirmation(_).
assistant_state(thinking) :- intent(query), \+ decide_action(_).

% Response Generation Rules
generate_response(informative) :- intent(query), decide_action(route_to_ai).
generate_response(action_confirmation) :- decide_action(_), \+ decide_action(route_to_ai).
generate_response(error_message) :- detect_error(_).
generate_response(help_response) :- user_intent(help).
generate_response(clarification_request) :- context_error(_).

% Multi-step Task Handling
task_step(1, open_browser) :- plan([open_browser, _]).
task_step(2, search_query) :- plan([_, search_query]).
task_step(1, set_reminder) :- plan([set_reminder, _]).
task_step(2, confirm) :- plan([_, confirm]).

% Assistant Learning Rules
learn_user_preference(youtube) :- token(open), token(youtube), decide_action(open_browser).
learn_user_preference(music) :- token(play), token(music), decide_action(play_music).
learn_user_preference(reminder) :- intent(reminder), should_remind(_, _).
learn_interaction_pattern(morning) :- token(good), token(morning).
learn_interaction_pattern(evening) :- token(good), token(evening).

% Assistant Error Handling
handle_error(no_target) :- detect_error(no_target), suggest(specify_target).
handle_error(invalid_time) :- detect_error(invalid_time), suggest(clarify_time).
handle_error(ambiguous_command) :- detect_error(ambiguous_command), suggest(choose_browser).
handle_error(context_mismatch) :- context_error(_), suggest(specify_context).

% Assistant Performance Optimization
optimize_response(quick) :- quick_decision(_).
optimize_response(detailed) :- intent(query), \+ quick_decision(_).
optimize_response(minimal) :- context_error(_).
optimize_response(comprehensive) :- plan(_).

% Assistant Personality Rules
personality(helpful) :- user_intent(help), generate_response(help_response).
personality(efficient) :- process_command(quick).
personality(thorough) :- process_command(complex).
personality(polite) :- assistant_response(acknowledgment).

% Context-Aware Assistant Behavior
contextual_response(browser_help) :- context(browser, _), user_intent(help).
contextual_response(app_guidance) :- context(app, _), user_intent(help).
contextual_response(general_help) :- active_context(none), user_intent(help).

% Assistant Memory Integration
use_memory(fact) :- intent(query), memory_note(_).
use_memory(precedent) :- context_error(_), learned_pattern(_).
use_memory(context) :- last_context(_), \+ active_context(_).

% Assistant Proactive Behavior
proactive_suggestion(reminder) :- context(browser, _), token(long), token(time).
proactive_suggestion(break) :- context(app, _), token(work), token(hours).
proactive_suggestion(save_work) :- context(app, _), token(important), token(document).

% Assistant Coordination Rules
coordinate_with_system(system_open) :- decide_action(system_open).
coordinate_with_browser(browser_action) :- decide_action(open_browser).
coordinate_with_reminder(reminder_set) :- decide_action(set_reminder).
coordinate_with_music(music_play) :- decide_action(play_music).

% Assistant Quality Assurance
quality_check(complete) :- decide_action(_), \+ detect_error(_).
quality_check(needs_clarification) :- detect_error(_), \+ handle_error(_).
quality_check(optimized) :- optimize_response(_), \+ context_error(_).

% Assistant Adaptation Rules
adapt_to_user(preferences) :- learned_pattern(_), learned_context_preference(_, _).
adapt_to_context(current) :- active_context(Context), compatible_context(Context, _).
adapt_to_situation(urgent) :- priority_decision(high).
adapt_to_situation(casual) :- priority_decision(low).

