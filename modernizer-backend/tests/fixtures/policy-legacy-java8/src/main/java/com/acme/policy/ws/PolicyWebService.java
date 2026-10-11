package com.acme.policy.ws;

import com.acme.policy.domain.Policy;
import com.acme.policy.search.PolicySearchService;
import com.acme.policy.service.PolicyService;
import java.util.List;
import javax.jws.WebMethod;
import javax.jws.WebParam;
import javax.jws.WebService;
import org.springframework.web.context.ContextLoader;

@WebService(serviceName = "PolicyService", targetNamespace = "http://acme.com/policy/ws")
public class PolicyWebService {

    private PolicyService service() {
        return ContextLoader.getCurrentWebApplicationContext().getBean(PolicyService.class);
    }

    @WebMethod(operationName = "getPolicy")
    public Policy getPolicy(@WebParam(name = "policyId") Long policyId) {
        return service().get(policyId);
    }

    @WebMethod(operationName = "searchPolicies")
    public List<String> searchPolicies(@WebParam(name = "holderName") String holderName) throws Exception {
        return ContextLoader.getCurrentWebApplicationContext().getBean(PolicySearchService.class)
                .searchByHolder(holderName, 50);
    }
}
