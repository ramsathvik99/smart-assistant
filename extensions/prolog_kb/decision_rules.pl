% ============================================
% CENTRAL REASONING ENGINE - DECISION RULES
% ============================================

% Conflict Detection
conflict(A, B, T) :- scheduled(A, T), scheduled(B, T).

% Enhanced Intent Detection (Advanced AI-style)
intent(open_app) :- token(open).
intent(search) :- token(search).
intent(reminder) :- token(remind).
intent(query) :- token(who); token(what); token(where); token(when); token(why); token(how).
intent(navigation) :- token(go), token(back).
intent(navigation) :- token(back).
intent(browser) :- token(youtube); token(chrome); token(firefox); token(edge); token(browser).
intent(system_open) :- token(open).
intent(system_close) :- token(close); token(terminate); token(shutdown).
intent(search) :- token(find).
intent(play) :- token(play).
intent(music) :- token(music); token(song); token(audio).

% Action Decision (Advanced AI Core)
decide_action(open_browser) :- intent(open_app), token(youtube).
decide_action(search_youtube) :- intent(search), token(youtube).
decide_action(set_reminder) :- intent(reminder).
decide_action(go_back) :- intent(navigation).
decide_action(answer_query) :- intent(query).
decide_action(open_chrome) :- intent(open_app), token(chrome).
decide_action(play_music) :- intent(play), intent(music).
decide_action(search_web) :- intent(search), \+ token(youtube).

% Multi-Step Planning (Advanced AI CORE)
plan([open_browser, search_query]) :- intent(open_app), intent(search), token(youtube).
plan([open_browser, play_video]) :- token(youtube), token(play).
plan([open_chrome, search_web]) :- intent(open_app), intent(search), token(chrome).
plan([set_reminder, confirm]) :- intent(reminder), token(please).
plan([play_music, confirm]) :- intent(play), intent(music).

% Enhanced Multi-Step Planning for Complex Goals
plan([close_distractions, open_vscode, play_focus_music]) :- token(focus), token(coding).
plan([open_vscode, open_project, play_music]) :- token(coding), token(prepare).
plan([open_browser, search_tutorial]) :- token(learn), token(coding).
plan([open_browser, search_documentation]) :- token(help), token(coding).
plan([open_vscode, open_terminal]) :- token(development), token(start).
plan([open_vscode, open_project_folder]) :- token(project), token(open).
plan([open_vscode, open_git, open_terminal]) :- token(git), token(start).
plan([open_vscode, open_extensions]) :- token(vscode), token(extensions).
plan([open_vscode, open_settings]) :- token(vscode), token(settings).

% Goal-Based Planning
goal(focus) :- token(focus).
goal(coding) :- token(coding); token(prepare).
goal(learning) :- token(learn); token(study).
goal(development) :- token(development); token(start).
goal(project) :- token(project).
goal(git) :- token(git).
goal(vscode) :- token(vscode).

% Goal-to-Plan Mapping
plan([close_distractions, open_vscode, play_focus_music]) :- goal(focus).
plan([open_vscode, open_project, play_music]) :- goal(coding).
plan([open_browser, search_tutorial]) :- goal(learning), goal(coding).
plan([open_browser, search_documentation]) :- goal(learning).
plan([open_vscode, open_terminal]) :- goal(development).
plan([open_vscode, open_project_folder]) :- goal(project).
plan([open_vscode, open_git, open_terminal]) :- goal(git).
plan([open_vscode, open_extensions]) :- goal(vscode).
plan([open_vscode, open_settings]) :- goal(vscode).

% Context-Aware Actions
decide_action(pause_video) :- token(pause), context(youtube).
decide_action(play_video) :- token(play), context(youtube).
decide_action(next_video) :- token(next), context(youtube).
decide_action(previous_video) :- token(previous), context(youtube).
decide_action(stop_video) :- token(stop), context(youtube).
decide_action(mute_video) :- token(mute), context(youtube).
decide_action(unmute_video) :- token(unmute), context(youtube).
decide_action(fullscreen_video) :- token(fullscreen), context(youtube).

% Enhanced Browser Navigation
decide_action(browser_back) :- token(back), context(browser).
decide_action(browser_forward) :- token(forward), context(browser).
decide_action(browser_refresh) :- token(refresh), context(browser).
decide_action(browser_home) :- token(home), context(browser).
decide_action(browser_new_tab) :- token(new), token(tab), context(browser).
decide_action(browser_close_tab) :- token(close), token(tab), context(browser).

% Quick Decision for single actions
quick_decision(open_browser) :- token(open), token(youtube).
quick_decision(go_back) :- token(back).
quick_decision(play_music) :- token(play), token(music).
quick_decision(search_web) :- token(search), \+ token(youtube).
intent(music) :- token(play), token(music).
intent(music) :- token(song).
intent(music) :- token(spotify).
intent(system_control) :- token(volume).
intent(system_control) :- token(mute).
intent(system_control) :- token(unmute).

% Action Decision Rules
decide_action(open_browser) :- intent(browser).
decide_action(open_browser) :- token(open), token(youtube).
decide_action(open_browser) :- token(open), token(chrome).
decide_action(open_browser) :- token(open), token(firefox).
decide_action(close_browser) :- intent(browser), token(close).
decide_action(close_browser) :- token(close), token(tab).
decide_action(navigate_back) :- intent(navigation).
decide_action(navigate_back) :- token(go), token(back).
decide_action(set_reminder) :- intent(reminder).
decide_action(search_web) :- intent(search).
decide_action(play_music) :- intent(music).
decide_action(system_control) :- intent(system_control).
decide_action(route_to_ai) :- intent(query).
decide_action(route_to_knowledge) :- token(who).
decide_action(route_to_knowledge) :- token(what).
decide_action(route_to_knowledge) :- token(where).
decide_action(route_to_knowledge) :- token(when).
decide_action(route_to_knowledge) :- token(why).
decide_action(route_to_knowledge) :- token(how).
decide_action(route_to_create_folder) :- token(create), token(folder).
decide_action(system_open) :- intent(system_open).
decide_action(system_close) :- intent(system_close).

% Command Refinement Rules
refined_command("open youtube") :- token(open), token(youtube).
refined_command("open chrome") :- token(open), token(chrome).
refined_command("close tab") :- token(close), token(tab).
refined_command("go back") :- token(go), token(back).
refined_command("search web") :- intent(search).

% Task Planning Rules (Multi-step)
plan([open_browser, search_query]) :- intent(browser), intent(search).
plan([open_browser, play_music]) :- token(open), token(youtube), intent(music).
plan([system_open, navigate_back]) :- intent(system_open), intent(navigation).
plan([set_reminder, confirm]) :- intent(reminder), token(please).
plan([search_web, extract_info]) :- intent(search), intent(query).

% Priority Decision Rules
priority_decision(high) :- token(urgent).
priority_decision(high) :- token(emergency).
priority_decision(medium) :- token(today).
priority_decision(medium) :- token(important).
priority_decision(low) :- token(later).
priority_decision(low) :- token(sometime).

% Context-Aware Decision Rules
context_decision(use_browser_back) :- context(browser, _), intent(navigation).
context_decision(use_app_back) :- context(app, _), intent(navigation).
context_decision(close_current) :- context(app, _), intent(system_close).
context_decision(switch_tab) :- context(browser, _), token(tab).

% Command Type Classification
command_type(system) :- intent(system_open).
command_type(system) :- intent(system_close).
command_type(system) :- intent(system_control).
command_type(browser) :- intent(browser).
command_type(reminder) :- intent(reminder).
command_type(music) :- intent(music).
command_type(query) :- intent(query).
command_type(navigation) :- intent(navigation).
command_type(search) :- intent(search).

% Ambiguity Resolution
resolve_ambiguous(open) :- token(youtube), decide_action(open_browser).
resolve_ambiguous(open) :- token(chrome), decide_action(open_browser).
resolve_ambiguous(close) :- token(tab), decide_action(close_browser).
resolve_ambiguous(close) :- context(browser, _), decide_action(close_browser).
resolve_ambiguous(play) :- token(music), decide_action(play_music).
resolve_ambiguous(play) :- token(song), decide_action(play_music).

% Error Detection and Recovery
detect_error(no_target) :- token(open), \+ token(_).
detect_error(no_target) :- token(close), \+ token(_).
detect_error(invalid_time) :- intent(reminder), \+ token(in), \+ token(at), \+ token(for).
detect_error(ambiguous_command) :- token(open), token(youtube), token(chrome).

% Suggestion Rules
suggest(reopen_last_app) :- last_app(Name), context(system, _).
suggest(open_browser) :- last_browser(Name), context(system, _).
suggest(stay_in_context) :- context(app, _).
suggest(use_web_context) :- context(browser, _).
suggest(clarify_time) :- intent(reminder), detect_error(invalid_time).
suggest(specify_target) :- detect_error(no_target).
suggest(choose_browser) :- detect_error(ambiguous_command).

% Confidence Scoring
confidence(high) :- decide_action(Action), \+ detect_error(_).
confidence(medium) :- decide_action(Action), suggest(_).
confidence(low) :- detect_error(_), \+ resolve_ambiguous(_).

% Learning and Adaptation
learned_pattern(open_youtube) :- token(open), token(youtube), decide_action(open_browser).
learned_pattern(close_tab) :- token(close), token(tab), decide_action(close_browser).
learned_pattern(navigate_back) :- token(go), token(back), decide_action(navigate_back).

% Performance Optimization
quick_decision(open_browser) :- token(open), token(youtube).
quick_decision(set_reminder) :- token(remind), token(in).
quick_decision(navigate_back) :- token(go), token(back).
quick_decision(search_web) :- token(search).
