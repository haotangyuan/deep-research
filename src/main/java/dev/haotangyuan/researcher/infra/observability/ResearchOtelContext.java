package dev.haotangyuan.researcher.infra.observability;

import io.opentelemetry.context.Context;
import io.opentelemetry.context.Scope;
import reactor.util.context.ContextView;

import java.util.ArrayDeque;
import java.util.Deque;

public final class ResearchOtelContext {
    public static final String REACTOR_CONTEXT_KEY = "deep_research.otel.context";
    private static final ThreadLocal<Deque<Context>> CONTEXT_STACK = ThreadLocal.withInitial(ArrayDeque::new);

    private ResearchOtelContext() {
    }

    public static Context current() {
        Deque<Context> stack = CONTEXT_STACK.get();
        if (!stack.isEmpty()) {
            return stack.peek();
        }
        return Context.current();
    }

    public static Context current(ContextView view) {
        if (view != null && view.hasKey(REACTOR_CONTEXT_KEY)) {
            return view.get(REACTOR_CONTEXT_KEY);
        }
        return current();
    }

    public static Scope makeCurrent(Context context) {
        Context resolved = context == null ? Context.current() : context;
        Scope otelScope = resolved.makeCurrent();
        CONTEXT_STACK.get().push(resolved);
        return () -> {
            Deque<Context> stack = CONTEXT_STACK.get();
            if (!stack.isEmpty()) {
                stack.pop();
            }
            otelScope.close();
            if (stack.isEmpty()) {
                CONTEXT_STACK.remove();
            }
        };
    }

    public static void clear() {
        CONTEXT_STACK.remove();
    }

    public static void restore(Context target) {
        Deque<Context> stack = CONTEXT_STACK.get();
        while (!stack.isEmpty() && !sameContext(stack.peek(), target)) {
            stack.pop();
        }
        if (stack.isEmpty() && target != null && target != Context.root()) {
            stack.push(target);
        }
        if (stack.isEmpty()) {
            CONTEXT_STACK.remove();
        }
    }

    private static boolean sameContext(Context left, Context right) {
        return left == right || (left != null && left.equals(right));
    }
}
