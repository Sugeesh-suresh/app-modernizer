package com.acme.inventory.util;

import com.acme.inventory.model.Product;
import java.io.IOException;
import java.io.Writer;
import java.util.List;

public class CsvExporter {
    public static final String HEADER = "id,sku,name,price,stock";

    public void write(List<Product> products, Writer out) throws IOException {
        out.write(HEADER);
        out.write("\n");
        for (Product p : products) {
            out.write(p.getId() + "," + escape(p.getSku()) + "," + escape(p.getName()) + ","
                    + (p.getPrice() == null ? "" : p.getPrice().toPlainString()) + "," + p.getStock() + "\n");
        }
        out.flush();
    }

    public String escape(String v) {
        if (v == null) {
            return "";
        }
        if (v.indexOf(',') >= 0 || v.indexOf('"') >= 0 || v.indexOf('\n') >= 0) {
            return "\"" + v.replace("\"", "\"\"") + "\"";
        }
        return v;
    }
}
