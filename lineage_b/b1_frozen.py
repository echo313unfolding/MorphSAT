"""Values filled ONLY at the B1 confirmatory freeze (prereg v1.5 §15 g).
Until then the confirmatory runner refuses to start."""

N = None                                  # from the frozen N rule (§7a), via the sizing receipt
CONFIRMATORY_SEED_LIST_SHA256 = None      # b1_seeds.seed_list_sha256("confirmatory", N)
SIZING_RECEIPT = None                     # path of the committed sizing receipt
