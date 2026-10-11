package com.acme.bank.config;

import com.acme.bank.soap.StatementService;
import javax.xml.ws.Endpoint;
import org.springframework.boot.web.servlet.ServletRegistrationBean;
import org.springframework.context.ApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.io.ClassPathResource;
import org.springframework.ws.config.annotation.EnableWs;
import org.springframework.ws.transport.http.MessageDispatcherServlet;
import org.springframework.ws.wsdl.wsdl11.DefaultWsdl11Definition;
import org.springframework.xml.xsd.SimpleXsdSchema;
import org.springframework.xml.xsd.XsdSchema;

@EnableWs
@Configuration
public class WebServiceConfig {

    @Bean
    public ServletRegistrationBean<MessageDispatcherServlet> messageDispatcherServlet(ApplicationContext context) {
        MessageDispatcherServlet servlet = new MessageDispatcherServlet();
        servlet.setApplicationContext(context);
        servlet.setTransformWsdlLocations(true);
        return new ServletRegistrationBean<>(servlet, "/ws/*");
    }

    @Bean(name = "accounts")
    public DefaultWsdl11Definition accountsWsdl(XsdSchema accountsSchema) {
        DefaultWsdl11Definition wsdl = new DefaultWsdl11Definition();
        wsdl.setPortTypeName("AccountsPort");
        wsdl.setLocationUri("/ws");
        wsdl.setTargetNamespace("http://acme.com/bank/accounts");
        wsdl.setSchema(accountsSchema);
        return wsdl;
    }

    @Bean
    public XsdSchema accountsSchema() {
        return new SimpleXsdSchema(new ClassPathResource("xsd/accounts.xsd"));
    }

    @Bean
    public Endpoint statementEndpoint(StatementService service) {
        return Endpoint.publish("http://0.0.0.0:8081/soap/statements", service);
    }
}
