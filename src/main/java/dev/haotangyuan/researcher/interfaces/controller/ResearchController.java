package dev.haotangyuan.researcher.interfaces.controller;

import dev.haotangyuan.researcher.infra.common.Result;
import dev.haotangyuan.researcher.infra.common.Results;
import dev.haotangyuan.researcher.infra.sse.SseHub;
import dev.haotangyuan.researcher.interfaces.dto.req.SendMessageReqDTO;
import dev.haotangyuan.researcher.interfaces.dto.resp.CreateResearchRespDTO;
import dev.haotangyuan.researcher.interfaces.dto.resp.ResearchMessageRespDTO;
import dev.haotangyuan.researcher.interfaces.dto.resp.ResearchStatusRespDTO;
import dev.haotangyuan.researcher.interfaces.dto.resp.SendMessageRespDTO;
import dev.haotangyuan.researcher.interfaces.service.ResearchService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.util.List;

/**
 * @author: haotangyuan
 */
@RestController
@RequiredArgsConstructor
public class ResearchController {

    private final ResearchService researchService;
    private final SseHub sseHub;

    @GetMapping("/api/v1/research/create")
    public Result<CreateResearchRespDTO> createResearch(
            @RequestAttribute("userId") Long userId, @RequestParam Integer num) {
        return Results.success(researchService.createResearch(userId, num));
    }

    @GetMapping("/api/v1/research/list")
    public Result<List<ResearchStatusRespDTO>> getResearchList(
            @RequestAttribute("userId") Long userId) {
        return Results.success(researchService.getResearchList(userId));
    }

    @GetMapping("/api/v1/research/{researchId}")
    public Result<ResearchStatusRespDTO> getResearchStatus(
            @RequestAttribute("userId") Long userId, @PathVariable String researchId) {
        return Results.success(researchService.getResearchStatus(userId, researchId));
    }

    @GetMapping("/api/v1/research/{researchId}/messages")
    public Result<ResearchMessageRespDTO> getResearchMessages(
            @RequestAttribute("userId") Long userId, @PathVariable String researchId) {
        return Results.success(researchService.getResearchMessages(userId, researchId));
    }

    @PostMapping("/api/v1/research/{researchId}/messages")
    public Result<SendMessageRespDTO> sendMessage(
            @RequestAttribute("userId") Long userId, @PathVariable String researchId,
            @RequestBody SendMessageReqDTO sendMessageReqDTO) {
        return Results.success(researchService.sendMessage(userId, researchId, sendMessageReqDTO));
    }

    @GetMapping("/api/v1/research/sse")
    public SseEmitter stream(@RequestAttribute("userId") Long userId,
             @RequestHeader("X-Research-Id") String researchId,
            @RequestHeader("X-Client-Id") String clientId, // 前端记得分配
            @RequestHeader(value = "Last-Event-ID", required = false) String lastEventId) {
        return sseHub.connect(userId, researchId, clientId, lastEventId);
    }
}
