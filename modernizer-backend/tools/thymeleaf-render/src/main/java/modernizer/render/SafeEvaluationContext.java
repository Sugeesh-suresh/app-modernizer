package modernizer.render;

import java.lang.reflect.Method;
import java.util.Arrays;
import java.util.List;
import org.springframework.context.ApplicationContext;
import org.springframework.expression.spel.SpelEvaluationException;
import org.springframework.expression.spel.SpelMessage;
import org.springframework.expression.spel.support.ReflectiveMethodResolver;
import org.thymeleaf.spring6.expression.ThymeleafEvaluationContext;

/**
 * The expression context every page is rendered with. Templates come from the
 * uploaded repository, and a Spring expression can reach Java code, so:
 * no type references (T(...)), no constructors (new ...), no bean references,
 * and no methods that lead to classes, class loaders, reflection, processes,
 * threads or the system.
 */
final class SafeEvaluationContext {
    private SafeEvaluationContext() {
    }

    static ThymeleafEvaluationContext create(ApplicationContext app) {
        ThymeleafEvaluationContext context = new ThymeleafEvaluationContext(app, null);
        context.setTypeLocator(name -> {
            throw new SpelEvaluationException(SpelMessage.TYPE_NOT_FOUND, name + " (type references are disabled)");
        });
        context.setConstructorResolvers(List.of());
        context.setBeanResolver(null);
        context.setMethodResolvers(List.of(new SafeMethodResolver()));
        // Sample objects are maps: ${job.name} reads the "name" entry.
        context.getPropertyAccessors().add(0, new LenientMapAccessor());
        return context;
    }

    static final class SafeMethodResolver extends ReflectiveMethodResolver {
        private static final List<Class<?>> BLOCKED = List.of(Class.class, ClassLoader.class, Runtime.class,
                ProcessBuilder.class, Process.class, System.class, Thread.class, ThreadGroup.class, Module.class);

        @Override
        protected Method[] getMethods(Class<?> type) {
            return Arrays.stream(super.getMethods(type)).filter(SafeMethodResolver::allowed).toArray(Method[]::new);
        }

        static boolean allowed(Method m) {
            if (m.getName().equals("getClass") || m.getName().equals("forName")) return false;
            Class<?> declaring = m.getDeclaringClass();
            String pkg = declaring.getPackageName();
            if (pkg.startsWith("java.lang.reflect") || pkg.startsWith("java.lang.invoke")
                    || pkg.startsWith("java.io") || pkg.startsWith("java.nio") || pkg.startsWith("java.net")) {
                return false;
            }
            return BLOCKED.stream().noneMatch(b -> b.isAssignableFrom(declaring));
        }
    }
}
