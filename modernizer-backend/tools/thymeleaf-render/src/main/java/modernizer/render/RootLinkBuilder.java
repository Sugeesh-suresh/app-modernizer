package modernizer.render;

import java.util.Map;
import org.thymeleaf.context.IExpressionContext;
import org.thymeleaf.linkbuilder.StandardLinkBuilder;

/** `@{/css/app.css}` becomes `/css/app.css`: the page is served at the root, with no servlet context path. */
final class RootLinkBuilder extends StandardLinkBuilder {
    @Override
    protected String computeContextPath(IExpressionContext context, String base, Map<String, Object> parameters) {
        return "";
    }
}
