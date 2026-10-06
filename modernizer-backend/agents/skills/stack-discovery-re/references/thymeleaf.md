# Thymeleaf server-rendered UI — what to document

Where to look:
- Templates: `src/main/resources/templates/**` (`*.html`), fragments and layouts (`th:fragment`, `th:replace`, `th:insert`, `layout:decorate`), message bundles (`messages*.properties`)
- Controllers that render them: `@Controller` classes, `@GetMapping`/`@PostMapping`/`@RequestMapping` handlers returning view names, `Model`/`ModelAndView` attributes, `@ModelAttribute`, redirects
- Static assets: `src/main/resources/static/**` — page scripts, CSS, images; committed vendor libraries under `vendor/`/`lib/` (list them; document application code, not library internals)
- Security in the views: `sec:authorize`, `sec:authentication`, `#authorization` expressions, CSRF tokens in forms
- Thymeleaf configuration: `spring.thymeleaf.*` properties, template resolvers, dialects

What to record:
- Every page: template path, the URL that renders it, the controller method that returns it, the model attributes it reads, its layout and fragments
- UI modules (folders such as `templates/<module>/`): what each module is for and which pages belong to it
- Forms: action URL, method, bound object (`th:object`/`th:field`), fields, validation messages shown, where they post and what happens next
- Conditional rendering (`th:if`, `th:unless`, `th:switch`) and what decides it — these are user-visible business rules
- Lists and empty states: each `th:each`, what it iterates, the row status variable used (`stat.odd`, `stat.last`) and what is shown when the list is empty (`#lists.isEmpty`)
- Styling and control states that carry meaning: `th:classappend`/`th:class`/`th:style` conditions (overdue rows, warnings) and `th:disabled`/`th:readonly`/`th:checked`/`th:selected`/`th:required` conditions — say what each state means to the user
- Formatting: every `#numbers`/`#dates`/`#temporals`/`#calendars` call with its pattern, decimals and locale — these are display rules a rebuilt UI must repeat exactly
- Forms and their errors: each `th:field` and the `th:errors`/`#fields.hasErrors` shown for it, with the validation that produces the message (the form object's constraints, the validator, `BindingResult.rejectValue`)
- Server calls from templates: `${@bean.method(..)}` expressions — the bean, method and what decision it makes for the page
- Ternaries and `th:text` expressions that choose wording or values (`cond ? 'Express' : 'Standard'`)
- Fragments and layouts: which pages include each fragment (header, menu, footer), so a rule in a fragment is recorded as applying to all of them
- Inline scripts (`<script th:inline="javascript">`, `[[${...}]]`): the values the server injects and every condition, validation and call in the script
- Who sees what: `sec:authorize` conditions, roles, and what they show or hide
- Page scripts: functions, client-side validations, AJAX/fetch calls and the endpoints they hit
- Navigation between pages, error pages, flash messages, internationalised text
- Tests covering the pages or their controllers (MockMvc, `@WebMvcTest`, Selenium) and what they need to run
