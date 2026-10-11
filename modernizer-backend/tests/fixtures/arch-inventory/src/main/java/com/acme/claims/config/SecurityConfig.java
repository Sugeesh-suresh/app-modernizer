package com.acme.claims.config;

@Configuration
@EnableWebSecurity
@EnableMethodSecurity
@EnableJpaAuditing
public class SecurityConfig {
    @Bean
    SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http.authorizeHttpRequests(a -> a
                .requestMatchers("/admin/**").hasRole("ADMIN")
                .requestMatchers("/actuator/health").permitAll()
                .anyRequest().authenticated())
            .formLogin(f -> f.loginPage("/login"))
            .csrf(c -> c.ignoringRequestMatchers("/api/**"))
            .sessionManagement(s -> s.maximumSessions(1));
        return http.build();
    }
    @Bean PasswordEncoder encoder() { return new BCryptPasswordEncoder(); }
}
