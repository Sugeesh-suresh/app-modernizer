package com.acme.claims.client;

public class PaymentClient {
    private final RestTemplate restTemplate = new RestTemplate();
    @Value("${payments.url}") String base;
    public void pay() { restTemplate.postForObject("${payments.url}/charges", null, String.class); }

    @JmsListener(destination = "claims.submitted")
    public void onClaim(String msg) { }
}
@FeignClient(name = "policy", url = "${policy.service-url}")
interface PolicyClient { }
