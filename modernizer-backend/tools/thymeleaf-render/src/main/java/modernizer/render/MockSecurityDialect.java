package modernizer.render;

import java.util.Set;
import org.springframework.expression.EvaluationContext;
import org.springframework.expression.spel.standard.SpelExpressionParser;
import org.springframework.expression.spel.support.SimpleEvaluationContext;
import org.thymeleaf.context.ITemplateContext;
import org.thymeleaf.dialect.AbstractProcessorDialect;
import org.thymeleaf.engine.AttributeName;
import org.thymeleaf.model.IProcessableElementTag;
import org.thymeleaf.processor.IProcessor;
import org.thymeleaf.processor.element.AbstractAttributeTagProcessor;
import org.thymeleaf.processor.element.IElementTagStructureHandler;
import org.thymeleaf.templatemode.TemplateMode;

/**
 * `sec:authorize`, `sec:authorize-expr`, `sec:authentication` (and a permissive
 * `sec:authorize-url`) evaluated against the sample user of the page's state —
 * not Spring Security itself, which needs a running web request. Only the
 * MockSecurity methods are reachable from these expressions.
 */
final class MockSecurityDialect extends AbstractProcessorDialect {
    static final String VARIABLE = "__modernizer_mock_security__";
    private static final SpelExpressionParser PARSER = new SpelExpressionParser();

    MockSecurityDialect() {
        super("Mock security", "sec", 1000);
    }

    @Override
    public Set<IProcessor> getProcessors(String prefix) {
        return Set.of(new Authorize(prefix, "authorize"), new Authorize(prefix, "authorize-expr"),
                new Authorize(prefix, "authorize-url"), new Authentication(prefix));
    }

    private static MockSecurity security(ITemplateContext context) {
        Object s = context.getVariable(VARIABLE);
        return s instanceof MockSecurity m ? m : new MockSecurity(java.util.List.of(), true);
    }

    private static String strip(String expression) {
        String e = expression == null ? "" : expression.trim();
        return e.startsWith("${") && e.endsWith("}") ? e.substring(2, e.length() - 1).trim() : e;
    }

    private static EvaluationContext evaluation(MockSecurity root) {
        return SimpleEvaluationContext.forReadOnlyDataBinding().withInstanceMethods().withRootObject(root).build();
    }

    static final class Authorize extends AbstractAttributeTagProcessor {
        private final boolean url;

        Authorize(String prefix, String attribute) {
            super(TemplateMode.HTML, prefix, null, false, attribute, true, 300, true);
            this.url = attribute.equals("authorize-url");
        }

        @Override
        protected void doProcess(ITemplateContext context, IProcessableElementTag tag, AttributeName name,
                                 String value, IElementTagStructureHandler handler) {
            if (url) return;   // URL rules live in the security configuration, not the page
            boolean visible;
            try {
                Object v = PARSER.parseExpression(strip(value)).getValue(evaluation(security(context)));
                visible = Boolean.TRUE.equals(v);
            } catch (RuntimeException e) {
                visible = true;   // an expression we cannot evaluate: show the element rather than hide it
            }
            if (!visible) handler.removeElement();
        }
    }

    static final class Authentication extends AbstractAttributeTagProcessor {
        Authentication(String prefix) {
            super(TemplateMode.HTML, prefix, null, false, "authentication", true, 1300, true);
        }

        @Override
        protected void doProcess(ITemplateContext context, IProcessableElementTag tag, AttributeName name,
                                 String value, IElementTagStructureHandler handler) {
            String text;
            try {
                Object v = PARSER.parseExpression(strip(value)).getValue(evaluation(security(context)));
                text = v == null ? "" : String.valueOf(v);
            } catch (RuntimeException e) {
                text = MockSecurity.Principal.USERNAME;
            }
            handler.setBody(text, false);
        }
    }
}
