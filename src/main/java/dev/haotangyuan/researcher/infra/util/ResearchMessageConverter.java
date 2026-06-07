package dev.haotangyuan.researcher.infra.util;

import dev.haotangyuan.researcher.application.agent.runtime.ResearchMessage;
import dev.haotangyuan.researcher.domain.entity.ChatMessage;

import java.util.ArrayList;
import java.util.List;

public final class ResearchMessageConverter {

    private ResearchMessageConverter() {
    }

    public static List<ResearchMessage> fromDbMessages(List<ChatMessage> dbMessages) {
        List<ResearchMessage> chatHistory = new ArrayList<>();
        for (ChatMessage msg : dbMessages) {
            if ("user".equals(msg.getRole())) {
                chatHistory.add(ResearchMessage.user(msg.getContent()));
            } else if ("assistant".equals(msg.getRole())) {
                chatHistory.add(ResearchMessage.assistant(msg.getContent()));
            }
        }
        return chatHistory;
    }
}
