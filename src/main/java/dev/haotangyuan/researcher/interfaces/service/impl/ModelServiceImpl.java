package dev.haotangyuan.researcher.interfaces.service.impl;

import dev.haotangyuan.researcher.domain.entity.Model;
import dev.haotangyuan.researcher.domain.mapper.ModelMapper;
import dev.haotangyuan.researcher.domain.mapper.ResearchSessionMapper;
import dev.haotangyuan.researcher.interfaces.dto.req.AddModelReqDTO;
import dev.haotangyuan.researcher.interfaces.dto.resp.ModelRespDTO;
import dev.haotangyuan.researcher.interfaces.service.ModelService;
import dev.haotangyuan.researcher.infra.exception.ModelException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;
import java.util.stream.Collectors;

/**
 * Model service implementation
 * @author: haotangyuan
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ModelServiceImpl implements ModelService {

    private final ResearchSessionMapper researchSessionMapper;
    private final ModelMapper modelMapper;
    
    @Override
    public List<ModelRespDTO> getAvailableModels(Long userId) {
        List<Model> models = modelMapper.selectAvailableModels(userId);
        
        return models.stream()
                .map(this::convertToRespDTO)
                .collect(Collectors.toList());
    }
    
    @Override
    public String addCustomModel(Long userId, AddModelReqDTO req) {
        if (req.getApiKey() == null || req.getBaseUrl() == null || req.getModel() == null) {
            throw new ModelException("模型信息不完整");
        }

        if (req.getName() == null) req.setName(req.getModel());

        Model model = Model.builder()
                .type("USER")
                .userId(userId)
                .name(req.getName())
                .model(req.getModel())
                .baseUrl(req.getBaseUrl())
                .apiKey(req.getApiKey())
                .createTime(LocalDateTime.now())
                .updateTime(LocalDateTime.now())
                .build();
        
        modelMapper.insert(model);
        
        log.info("用户 {} 添加自定义模型: {}", userId, model.getId());
        return model.getId();
    }
    
    @Override
    public void deleteCustomModel(Long userId, String modelId) {
        Model model = modelMapper.selectById(modelId);
        if (model == null) {
            throw new ModelException("模型不存在");
        }
        
        if (!"USER".equals(model.getType()) || !userId.equals(model.getUserId())) {
            throw new ModelException("无权删除此模型");
        }
        
        int activeUsage = researchSessionMapper.countActiveUsage(modelId);
        if (activeUsage > 0) {
            throw new ModelException("模型正在使用中，无法删除");
        }
        
        modelMapper.deleteById(modelId);
        log.info("用户 {} 删除自定义模型: {}", userId, modelId);
    }
    
    @Override
    public Model getModelById(Long userId, String modelId) {
        Model model = modelMapper.selectById(modelId);
        if (model == null) {
            throw new ModelException("模型不存在");
        }
        
        if ("GLOBAL".equals(model.getType()) || 
            ("USER".equals(model.getType()) && userId.equals(model.getUserId()))) {
            return model;
        }
        
        throw new ModelException("无权访问此模型");
    }
    
    private ModelRespDTO convertToRespDTO(Model model) {
        return ModelRespDTO.builder()
                .id(model.getId())
                .type(model.getType())
                .name(model.getName())
                .model(model.getModel())
                .baseUrl(model.getBaseUrl())
                .build();
    }
}
