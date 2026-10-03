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
- Who sees what: `sec:authorize` conditions, roles, and what they show or hide
- Page scripts: functions, client-side validations, AJAX/fetch calls and the endpoints they hit
- Navigation between pages, error pages, flash messages, internationalised text
- Tests covering the pages or their controllers (MockMvc, `@WebMvcTest`, Selenium) and what they need to run
