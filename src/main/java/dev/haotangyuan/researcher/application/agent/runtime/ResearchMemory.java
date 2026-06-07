package dev.haotangyuan.researcher.application.agent.runtime;

import java.util.ArrayList;
import java.util.List;

public class ResearchMemory {
    private final int maxMessages;
    private final List<ResearchMessage> messages = new ArrayList<>();

    public ResearchMemory(int maxMessages) {
        this.maxMessages = maxMessages;
    }

    public void add(ResearchMessage message) {
        messages.add(message);
        trim();
    }

    public void addAll(List<ResearchMessage> newMessages) {
        messages.addAll(newMessages);
        trim();
    }

    public List<ResearchMessage> messages() {
        return List.copyOf(messages);
    }

    public void clear() {
        messages.clear();
    }

    private void trim() {
        while (messages.size() > maxMessages) {
            messages.removeFirst();
        }
    }
}
