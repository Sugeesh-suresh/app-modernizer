# Browser front end (Backbone, React, Angular, AngularJS, Vue, Ember, Ext JS, jQuery) — what to document

Where to look:
- Manifests and tooling: `package.json`, `bower.json`, lockfiles, `webpack.config.*`, `vite.config.*`, `Gruntfile.js`, `Gulpfile.js`, RequireJS config (`require.config`, `data-main`), Babel/TypeScript config, `angular.json`
- Entry points: the HTML/JSP pages that load the scripts, the `main`/`app` module, bootstrapping code (`Backbone.history.start`, `ReactDOM.render`/`createRoot`, `platformBrowserDynamic`, `new Vue`/`createApp`, `angular.module`)
- Source: models, collections, views, components, routers/routes, services/stores, templates (Underscore/Handlebars/Mustache/JSX/HTML templates), styles
- Committed third-party libraries under `lib/`, `vendor/` and similar — list them, but document application code, not library internals

What to record:
- How the front end is built and loaded: build tool, module system (RequireJS/AMD, CommonJS, ES modules), bundles, and the pages that include them
- Every route/screen: URL or hash route, the view/component that renders it, and what it shows
- Components/views: responsibility, the model or state they render, the events they handle, and the templates they use
- Data layer: models, collections, stores or services; their fields; the REST endpoints they call (URL, method, payload, response), and how responses are mapped
- Client-side business rules: validations, calculations, formatting, conditional display, permissions checks
- State and navigation: routers, history handling, local/session storage, cookies, global objects
- Integration with the server-rendered pages (JSP or otherwise): data passed into the page, DOM the scripts take over, shared templates
- Third-party libraries in use and what the application uses each for
- Tests: framework (Jasmine, Mocha, QUnit, Jest, Karma, Cypress), what each suite covers, how it is run
