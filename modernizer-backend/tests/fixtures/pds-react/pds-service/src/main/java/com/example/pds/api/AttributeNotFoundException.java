package com.example.pds.api;
public class AttributeNotFoundException extends RuntimeException { public AttributeNotFoundException(Long id) { super("No attribute " + id); } }
