package modernizer.render;

import java.util.Arrays;
import java.util.List;

/** The sample signed-in user `sec:` attributes are evaluated against. Methods mirror Spring Security's expression root. */
public final class MockSecurity {
    private final List<String> roles;
    private final boolean authenticated;

    MockSecurity(List<String> roles, boolean authenticated) {
        this.roles = roles.stream().map(MockSecurity::bare).toList();
        this.authenticated = authenticated;
    }

    private static String bare(String role) {
        return role.startsWith("ROLE_") ? role.substring(5) : role;
    }

    public boolean hasRole(String role) { return authenticated && roles.contains(bare(role)); }
    public boolean hasAnyRole(String... any) { return Arrays.stream(any).anyMatch(this::hasRole); }
    public boolean hasAuthority(String authority) { return hasRole(authority); }
    public boolean hasAnyAuthority(String... any) { return hasAnyRole(any); }
    public boolean isAuthenticated() { return authenticated; }
    public boolean isFullyAuthenticated() { return authenticated; }
    public boolean isRememberMe() { return false; }
    public boolean isAnonymous() { return !authenticated; }
    public boolean isPermitAll() { return true; }
    public boolean isDenyAll() { return false; }
    public Principal getPrincipal() { return new Principal(); }
    public String getName() { return authenticated ? Principal.USERNAME : "anonymousUser"; }
    public List<String> getAuthorities() { return roles.stream().map(r -> "ROLE_" + r).toList(); }

    public static final class Principal {
        static final String USERNAME = "sample.user";
        public String getUsername() { return USERNAME; }
        public String getName() { return USERNAME; }
    }
}
