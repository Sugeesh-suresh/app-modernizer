package com.example.pds.service;
import com.example.pds.dto.AttributeDto;
import org.springframework.data.domain.Page;
import java.util.Optional;
public interface AttributeService {
    Page<AttributeDto> list(int page, int size, boolean showValues);
    Page<AttributeDto> search(Long id, String name, int page);
    Optional<AttributeDto> find(Long id);
}
