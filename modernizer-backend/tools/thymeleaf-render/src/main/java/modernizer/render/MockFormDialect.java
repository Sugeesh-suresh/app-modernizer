package modernizer.render;

import java.util.Collection;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.thymeleaf.context.IExpressionContext;
import org.thymeleaf.context.ITemplateContext;
import org.thymeleaf.dialect.AbstractProcessorDialect;
import org.thymeleaf.dialect.IExpressionObjectDialect;
import org.thymeleaf.engine.AttributeName;
import org.thymeleaf.expression.IExpressionObjectFactory;
import org.thymeleaf.model.IProcessableElementTag;
import org.thymeleaf.processor.IProcessor;
import org.thymeleaf.processor.element.AbstractAttributeTagProcessor;
import org.thymeleaf.processor.element.IElementTagStructureHandler;
import org.thymeleaf.standard.expression.StandardExpressions;
import org.thymeleaf.templatemode.TemplateMode;

/**
 * Form binding without a web request. Spring's `th:field` / `th:errors` /
 * `#fields` read a BindingResult that only exists while a request is handled;
 * here `th:field` fills name, id and value (checked for check boxes and radio
 * buttons, body for text areas) from the sample form object, `th:errors`
 * renders nothing, and `#fields` reports no errors — the page as first shown.
 * Runs before the Spring processors and removes the attribute it handles.
 */
final class MockFormDialect extends AbstractProcessorDialect implements IExpressionObjectDialect {
    MockFormDialect() {
        super("Mock form binding", "th", 900);
    }

    @Override
    public Set<IProcessor> getProcessors(String prefix) {
        return Set.of(new Field(prefix), new Errors(prefix, "errors"), new Errors(prefix, "errorclass"));
    }

    @Override
    public IExpressionObjectFactory getExpressionObjectFactory() {
        return new IExpressionObjectFactory() {
            @Override
            public Set<String> getAllExpressionObjectNames() {
                return Set.of("fields");
            }

            @Override
            public Object buildObject(IExpressionContext context, String name) {
                return new NoErrors();
            }

            @Override
            public boolean isCacheable(String name) {
                return true;
            }
        };
    }

    /** `#fields` for a form shown before any submission: nothing has errors. */
    public static final class NoErrors {
        public boolean hasErrors(Object field) { return false; }
        public boolean hasAnyErrors() { return false; }
        public boolean hasGlobalErrors() { return false; }
        public boolean hasErrors() { return false; }
        public List<String> errors(Object field) { return List.of(); }
        public List<String> allErrors() { return List.of(); }
        public List<String> globalErrors() { return List.of(); }
        public List<String> detailedErrors() { return List.of(); }
        public String idFromName(Object name) { return String.valueOf(name).replaceAll("[\\[\\].]", ""); }
    }

    static final class Field extends AbstractAttributeTagProcessor {
        Field(String prefix) {
            super(TemplateMode.HTML, prefix, null, false, "field", true, 10, true);
        }

        @Override
        protected void doProcess(ITemplateContext context, IProcessableElementTag tag, AttributeName attributeName,
                                 String expression, IElementTagStructureHandler handler) {
            String path = expression.trim().replaceAll("^[*$]\\{\\s*|\\s*}$", "");
            Object value;
            try {
                value = StandardExpressions.getExpressionParser(context.getConfiguration())
                        .parseExpression(context, expression).execute(context);
            } catch (RuntimeException e) {
                value = null;
            }
            if (!tag.hasAttribute("name")) handler.setAttribute("name", path);
            if (!tag.hasAttribute("id")) handler.setAttribute("id", path.replaceAll("[\\[\\].]", ""));
            String element = tag.getElementCompleteName().toLowerCase();
            String type = tag.hasAttribute("type") ? tag.getAttributeValue("type").toLowerCase() : "text";
            if (element.equals("textarea")) {
                handler.setBody(value == null ? "" : String.valueOf(value), false);
            } else if (element.equals("input") && (type.equals("checkbox") || type.equals("radio"))) {
                String own = tag.hasAttribute("value") ? tag.getAttributeValue("value") : null;
                boolean checked = own == null ? Boolean.TRUE.equals(value)
                        : value instanceof Collection<?> c ? c.stream().anyMatch(v -> own.equals(String.valueOf(v)))
                        : own.equals(String.valueOf(value));
                if (checked) handler.setAttribute("checked", "checked");
            } else if (element.equals("input") && !type.equals("password") && !type.equals("file")) {
                if (value != null && !(value instanceof Map)) handler.setAttribute("value", String.valueOf(value));
            }
        }
    }

    static final class Errors extends AbstractAttributeTagProcessor {
        private final boolean element;

        Errors(String prefix, String attribute) {
            super(TemplateMode.HTML, prefix, null, false, attribute, true, 10, true);
            this.element = attribute.equals("errors");
        }

        @Override
        protected void doProcess(ITemplateContext context, IProcessableElementTag tag, AttributeName attributeName,
                                 String expression, IElementTagStructureHandler handler) {
            if (element) handler.removeElement();
        }
    }
}
