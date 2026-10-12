package com.acme.store;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.cache.annotation.EnableCaching;

@SpringBootApplication
@EnableCaching
public class StorefrontApplication {
    public static void main(String[] args) {
        SpringApplication.run(StorefrontApplication.class, args);
    }
}
