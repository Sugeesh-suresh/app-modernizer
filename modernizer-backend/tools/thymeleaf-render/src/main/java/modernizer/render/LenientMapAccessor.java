package modernizer.render;

import java.util.Map;
import org.springframework.expression.EvaluationContext;
import org.springframework.expression.PropertyAccessor;
import org.springframework.expression.TypedValue;

/**
 * Reads a sample object's (a map's) entries as properties; a key that is not
 * there reads as null, as an unset request parameter or bean property would,
 * instead of failing the page. Read-only.
 */
final class LenientMapAccessor implements PropertyAccessor {
    @Override
    public Class<?>[] getSpecificTargetClasses() {
        return new Class<?>[] {Map.class};
    }

    @Override
    public boolean canRead(EvaluationContext context, Object target, String name) {
        return target instanceof Map;
    }

    @Override
    public TypedValue read(EvaluationContext context, Object target, String name) {
        return new TypedValue(((Map<?, ?>) target).get(name));
    }

    @Override
    public boolean canWrite(EvaluationContext context, Object target, String name) {
        return false;
    }

    @Override
    public void write(EvaluationContext context, Object target, String name, Object newValue) {
        throw new UnsupportedOperationException("sample data is read-only");
    }
}
