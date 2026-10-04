package modernizer.render;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.io.File;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.Date;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import nz.net.ultraq.thymeleaf.layoutdialect.LayoutDialect;
import org.springframework.context.support.GenericApplicationContext;
import org.springframework.context.support.ReloadableResourceBundleMessageSource;
import org.thymeleaf.context.Context;
import org.thymeleaf.spring6.SpringTemplateEngine;
import org.thymeleaf.spring6.expression.ThymeleafEvaluationContext;
import org.thymeleaf.templatemode.TemplateMode;
import org.thymeleaf.templateresolver.FileTemplateResolver;

/**
 * Renders Thymeleaf templates with sample data, one page per job.
 *
 * <pre>java -jar thymeleaf-render.jar jobs.json results.json</pre>
 *
 * jobs.json: {"templates": dir, "messages": [basename, ...],
 *             "jobs": [{"id", "template", "model", "roles", "authenticated", "out"}]}
 * results.json: [{"id", "ok", "error"}] — one failing page never stops the others.
 *
 * Model values are JSON; {"$date": "2026-01-15T10:30:00"} becomes a LocalDateTime
 * (LocalDate for a date only), with "$type": "java.util.Date" a Date.
 */
public final class Main {
    private static final ObjectMapper JSON = new ObjectMapper();

    public static void main(String[] args) throws Exception {
        if (args.length != 2) {
            System.err.println("usage: thymeleaf-render jobs.json results.json");
            System.exit(2);
        }
        JsonNode spec = JSON.readTree(new File(args[0]));
        GenericApplicationContext app = new GenericApplicationContext();
        app.refresh();

        SpringTemplateEngine engine = new SpringTemplateEngine();
        FileTemplateResolver resolver = new FileTemplateResolver();
        resolver.setPrefix(spec.get("templates").asText() + File.separator);
        resolver.setSuffix(".html");
        resolver.setTemplateMode(TemplateMode.HTML);
        resolver.setCharacterEncoding("UTF-8");
        resolver.setCacheable(false);
        resolver.setCheckExistence(true);
        engine.setTemplateResolver(resolver);
        engine.setLinkBuilder(new RootLinkBuilder());
        engine.setEnableSpringELCompiler(false);
        engine.addDialect(new LayoutDialect());
        engine.addDialect(new MockSecurityDialect());
        engine.addDialect(new MockFormDialect());

        ReloadableResourceBundleMessageSource messages = new ReloadableResourceBundleMessageSource();
        List<String> basenames = new ArrayList<>();
        for (JsonNode b : spec.path("messages")) {
            basenames.add("file:" + b.asText());
        }
        messages.setBasenames(basenames.toArray(new String[0]));
        messages.setDefaultEncoding("UTF-8");
        messages.setUseCodeAsDefaultMessage(true);
        messages.setFallbackToSystemLocale(false);
        engine.setTemplateEngineMessageSource(messages);

        List<Map<String, Object>> results = new ArrayList<>();
        for (JsonNode job : spec.path("jobs")) {
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("id", job.get("id").asText());
            try {
                Context context = new Context(Locale.US);
                Object model = convert(job.path("model"));
                if (model instanceof Map<?, ?> map) {
                    for (Map.Entry<?, ?> e : map.entrySet()) {
                        context.setVariable(String.valueOf(e.getKey()), e.getValue());
                    }
                }
                // Request parameters and the HTTP session exist only in a web
                // request; empty maps make ${param.x} / ${session.x} read as absent.
                if (!context.containsVariable("param")) context.setVariable("param", new LinkedHashMap<>());
                if (!context.containsVariable("session")) context.setVariable("session", new LinkedHashMap<>());
                context.setVariable(ThymeleafEvaluationContext.THYMELEAF_EVALUATION_CONTEXT_CONTEXT_VARIABLE_NAME,
                        SafeEvaluationContext.create(app));
                List<String> roles = new ArrayList<>();
                job.path("roles").forEach(r -> roles.add(r.asText()));
                context.setVariable(MockSecurityDialect.VARIABLE,
                        new MockSecurity(roles, job.path("authenticated").asBoolean(true)));
                String html = engine.process(job.get("template").asText(), context);
                Path out = Path.of(job.get("out").asText());
                Files.createDirectories(out.getParent());
                Files.writeString(out, html, StandardCharsets.UTF_8);
                result.put("ok", true);
            } catch (Exception | StackOverflowError e) {
                result.put("ok", false);
                result.put("error", rootMessage(e));
            }
            results.add(result);
        }
        JSON.writerWithDefaultPrettyPrinter().writeValue(new File(args[1]), results);
        app.close();
    }

    private static String rootMessage(Throwable e) {
        String first = e.getMessage();
        Throwable t = e;
        while (t.getCause() != null && t.getCause() != t) t = t.getCause();
        String root = t.getMessage();
        String msg = first == null ? String.valueOf(root) : (root == null || first.contains(root) ? first : first + " — " + root);
        msg = msg.replaceAll("\\s+", " ");
        return msg.length() > 400 ? msg.substring(0, 399) + "…" : msg;
    }

    static Object convert(JsonNode node) {
        if (node == null || node.isNull() || node.isMissingNode()) return null;
        if (node.isObject()) {
            if (node.has("$date")) {
                String v = node.get("$date").asText();
                if ("java.util.Date".equals(node.path("$type").asText())) {
                    LocalDateTime t = v.length() == 10 ? LocalDate.parse(v).atStartOfDay() : LocalDateTime.parse(v);
                    return Date.from(t.toInstant(ZoneOffset.UTC));
                }
                return v.length() == 10 ? LocalDate.parse(v) : LocalDateTime.parse(v);
            }
            Map<String, Object> map = new LinkedHashMap<>();
            Iterator<Map.Entry<String, JsonNode>> it = ((ObjectNode) node).fields();
            while (it.hasNext()) {
                Map.Entry<String, JsonNode> e = it.next();
                map.put(e.getKey(), convert(e.getValue()));
            }
            return map;
        }
        if (node.isArray()) {
            List<Object> list = new ArrayList<>();
            node.forEach(n -> list.add(convert(n)));
            return list;
        }
        if (node.isBoolean()) return node.asBoolean();
        if (node.isIntegralNumber()) return node.canConvertToInt() ? (Object) node.asInt() : (Object) node.asLong();
        if (node.isNumber()) return new BigDecimal(node.asText());
        return node.asText();
    }
}
