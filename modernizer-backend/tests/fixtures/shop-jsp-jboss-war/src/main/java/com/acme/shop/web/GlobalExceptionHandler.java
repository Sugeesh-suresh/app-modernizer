package com.acme.shop.web;

import com.acme.shop.service.DuplicateSkuException;
import com.acme.shop.service.InsufficientStockException;
import com.acme.shop.service.ProductNotFoundException;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.ControllerAdvice;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.servlet.ModelAndView;

@ControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(ProductNotFoundException.class)
    @ResponseStatus(HttpStatus.NOT_FOUND)
    public ModelAndView notFound(ProductNotFoundException e) {
        return error(e.getMessage());
    }

    @ExceptionHandler({InsufficientStockException.class, DuplicateSkuException.class})
    @ResponseStatus(HttpStatus.CONFLICT)
    public ModelAndView conflict(RuntimeException e) {
        return error(e.getMessage());
    }

    private ModelAndView error(String message) {
        ModelAndView mav = new ModelAndView("error");
        mav.addObject("errorMessage", message);
        return mav;
    }
}
