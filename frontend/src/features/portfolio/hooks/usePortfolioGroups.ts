/**
 * Portfolio groups CRUD hook.
 *
 * Wraps the groups list query and create/update/delete/reorder mutations,
 * keeping cache invalidation in one place. Shared with QuantTradingPage via
 * the ["portfolioGroups"] / ["portfolioGroupItems"] query keys. Create /
 * update / delete surface a toast; reorder is silent (too frequent).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createPortfolioGroup,
  deletePortfolioGroup,
  fetchPortfolioGroups,
  reorderPortfolioGroups,
  updatePortfolioGroup,
} from "@/api/quant";
import { useToast } from "@/components/ui/toast";

export const PORTFOLIO_GROUPS_KEY = ["portfolioGroups"] as const;

export function usePortfolioGroups() {
  const queryClient = useQueryClient();
  const toast = useToast();

  const query = useQuery({
    queryKey: PORTFOLIO_GROUPS_KEY,
    queryFn: fetchPortfolioGroups,
    staleTime: 30_000,
  });
  const groups = query.data?.items ?? [];

  const createMutation = useMutation({
    mutationFn: (name: string) =>
      createPortfolioGroup({
        name,
        group_type: "manual",
        description: "用户手动维护的持仓分组",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PORTFOLIO_GROUPS_KEY });
      toast({ title: "分组已创建", variant: "success" });
    },
    onError: (error) => toast({ title: "创建分组失败", description: error.message, variant: "error" }),
  });

  const updateMutation = useMutation({
    mutationFn: ({
      groupId,
      payload,
    }: {
      groupId: number;
      payload: Parameters<typeof updatePortfolioGroup>[1];
    }) => updatePortfolioGroup(groupId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PORTFOLIO_GROUPS_KEY });
      toast({ title: "分组已更新", variant: "success" });
    },
    onError: (error) => toast({ title: "更新分组失败", description: error.message, variant: "error" }),
  });

  const deleteMutation = useMutation({
    mutationFn: (groupId: number) => deletePortfolioGroup(groupId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PORTFOLIO_GROUPS_KEY });
      // Deleting a group also affects its items cache (prefix invalidation).
      queryClient.invalidateQueries({ queryKey: ["portfolioGroupItems"] });
      toast({ title: "分组已删除", variant: "success" });
    },
    onError: (error) => toast({ title: "删除分组失败", description: error.message, variant: "error" }),
  });

  const reorderMutation = useMutation({
    mutationFn: (groupIds: number[]) => reorderPortfolioGroups(groupIds),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: PORTFOLIO_GROUPS_KEY }),
  });

  return {
    groups,
    isLoading: query.isLoading,
    isError: query.isError,
    refetch: query.refetch,
    createGroup: createMutation.mutate,
    isCreating: createMutation.isPending,
    updateGroup: updateMutation.mutate,
    isUpdating: updateMutation.isPending,
    deleteGroup: deleteMutation.mutate,
    isDeleting: deleteMutation.isPending,
    reorderGroups: reorderMutation.mutate,
    isReordering: reorderMutation.isPending,
  };
}
