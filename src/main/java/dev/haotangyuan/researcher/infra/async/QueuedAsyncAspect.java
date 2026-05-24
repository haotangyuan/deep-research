package dev.haotangyuan.researcher.infra.async;

import dev.haotangyuan.researcher.application.state.DeepResearchState;
import dev.haotangyuan.researcher.infra.exception.ResearchException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.springframework.stereotype.Component;

/**
 * QueuedAsync 注解切面，拦截方法调用并提交到线程池
 * @author haotangyuan
 */
@Aspect
@Component
@RequiredArgsConstructor
@Slf4j
public class QueuedAsyncAspect {

    private final ResearchTaskExecutor researchTaskExecutor;

    @Around("@annotation(QueuedAsync)")
    public Object around(ProceedingJoinPoint joinPoint) throws Throwable {
        Object[] args = joinPoint.getArgs();
        if (args.length == 0 || !(args[0] instanceof DeepResearchState state)) {
            throw new ResearchException("@QueuedAsync 方法的第一个参数必须是 DeepResearchState");
        }

        String researchId = state.getResearchId();
        researchTaskExecutor.submit(researchId, () -> {
            try {
                joinPoint.proceed();
            } catch (Throwable e) {
                log.error("异步任务执行失败，researchId={}", researchId, e);
            }
        });
        return null;
    }
}
