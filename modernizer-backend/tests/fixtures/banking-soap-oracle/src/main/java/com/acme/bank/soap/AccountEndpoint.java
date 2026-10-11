package com.acme.bank.soap;

import com.acme.bank.accounts.GetAccountRequest;
import com.acme.bank.accounts.GetAccountResponse;
import com.acme.bank.accounts.TransferFundsRequest;
import com.acme.bank.accounts.TransferFundsResponse;
import com.acme.bank.domain.BalanceView;
import com.acme.bank.service.AccountService;
import org.springframework.ws.server.endpoint.annotation.Endpoint;
import org.springframework.ws.server.endpoint.annotation.PayloadRoot;
import org.springframework.ws.server.endpoint.annotation.RequestPayload;
import org.springframework.ws.server.endpoint.annotation.ResponsePayload;

@Endpoint
public class AccountEndpoint {
    private static final String NAMESPACE_URI = "http://acme.com/bank/accounts";

    private final AccountService accounts;

    public AccountEndpoint(AccountService accounts) {
        this.accounts = accounts;
    }

    @PayloadRoot(namespace = NAMESPACE_URI, localPart = "GetAccountRequest")
    @ResponsePayload
    public GetAccountResponse getAccount(@RequestPayload GetAccountRequest request) {
        BalanceView view = accounts.balance(request.getAccountNumber());
        GetAccountResponse response = new GetAccountResponse();
        response.setAccountNumber(view.accountNumber);
        response.setBalance(view.balance);
        response.setStatus(view.status);
        return response;
    }

    @PayloadRoot(namespace = NAMESPACE_URI, localPart = "TransferFundsRequest")
    @ResponsePayload
    public TransferFundsResponse transferFunds(@RequestPayload TransferFundsRequest request) {
        TransferFundsResponse response = new TransferFundsResponse();
        try {
            response.setTransferId(accounts.transfer(request.getFromAccount(), request.getToAccount(), request.getAmount()));
            response.setStatus("BOOKED");
        } catch (Exception e) {
            e.printStackTrace();
            response.setStatus("REJECTED");
        }
        return response;
    }
}
