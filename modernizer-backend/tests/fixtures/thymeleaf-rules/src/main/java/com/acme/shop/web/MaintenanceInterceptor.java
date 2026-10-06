package com.acme.shop.web;
public class MaintenanceInterceptor implements HandlerInterceptor {
    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) throws Exception {
        if (maintenance && !request.isUserInRole("ADMIN")) {
            response.sendRedirect("/maintenance");
            return false;
        }
        return true;
    }
}
