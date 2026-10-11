CREATE TABLE categories (
  code  VARCHAR2(20) PRIMARY KEY,
  name  VARCHAR2(100) NOT NULL
);
CREATE TABLE products (
  sku          VARCHAR2(30) PRIMARY KEY,
  name         VARCHAR2(200) NOT NULL,
  description  CLOB,
  category     VARCHAR2(20) REFERENCES categories(code),
  price        NUMBER(10,2) NOT NULL,
  in_stock     NUMBER(1) DEFAULT 1,
  updated_at   TIMESTAMP DEFAULT SYSTIMESTAMP
);
CREATE INDEX ix_products_updated ON products(updated_at);
