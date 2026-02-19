import torch
import torch.nn as nn
import numpy as np
from gymnasium import spaces
from sb3_contrib.common.maskable.policies import MaskableActorCriticPolicy
from stable_baselines3.common.distributions import CategoricalDistribution

class ParcelScoringPolicy(MaskableActorCriticPolicy):
    """
    Custom policy for land use optimization.
    
    Architecture:
      - Value Net: Input (Global features), Output (Value).
      - Scorer Net: Input (Parcel features + Global features), Output (Logit per parcel).
      
    This allows the model to handle a variable number of parcels (in principle) 
    and share weights across all parcel scoring decisions (Permutation Invariant).
    """

    def __init__(self, observation_space, action_space, lr_schedule,
                 k_parcel=6, k_global=8,
                 scorer_hiddens=[128, 64], value_hiddens=[128, 64],
                 **kwargs):
        self.k_parcel = k_parcel
        self.k_global = k_global
        self.scorer_hiddens = scorer_hiddens
        self.value_hiddens = value_hiddens
        
        super().__init__(observation_space, action_space, lr_schedule, **kwargs)

        # Re-build custom networks AFTER super().__init__ to override SB3 defaults
        # SB3 _build() creates self.value_net as nn.Linear and self.action_net
        # We replace them with our custom architecture to match the saved model
        
        # Scorer Net: (K_parcel + K_global) -> Logit
        self.scorer_net = self._build_sequential(
            self.k_parcel + self.k_global, 
            self.scorer_hiddens
        )
        
        # Value Net: (K_global) -> Value
        self.value_net = self._build_sequential(
            self.k_global, 
            self.value_hiddens
        )
        
        # Remove action_net as we don't use it and it's not in the saved state_dict
        if hasattr(self, 'action_net'):
            del self.action_net

    def _build_mlp_extractor(self):
        """
        Construct the Scorer Net and Value Net.
        Overrides the default SB3 MLP extractor.
        """
        # SB3 requires these attributes, set them to Identity or dummy
        self.mlp_extractor = nn.Identity()
        self.mlp_extractor.latent_dim_pi = 1 # Dummy dimension to satisfy SB3 initialization
        self.mlp_extractor.latent_dim_vf = 1 # Dummy dimension
        
    def _build_sequential(self, in_dim, hiddens):
        layers = []
        last = in_dim
        for h in hiddens:
            layers.append(nn.Linear(last, h))
            layers.append(nn.Tanh())
            last = h
        layers.append(nn.Linear(last, 1))
        return nn.Sequential(*layers)

    def forward(self, obs, deterministic=False, action_masks=None):
        """
        Forward pass for the policy.
        """
        # 1. Parse Observation
        # obs shape: [Batch, N*Kp + Kg]
        batch_size = obs.shape[0]
        n_swappable = (obs.shape[1] - self.k_global) // self.k_parcel
        
        # Extract global features: [Batch, Kg]
        global_features = obs[:, -self.k_global:]
        
        # Extract parcel features: [Batch, N, Kp]
        parcel_flat = obs[:, :-self.k_global]
        parcel_features = parcel_flat.view(batch_size, n_swappable, self.k_parcel)
        
        # 2. Value Estimate
        values = self.value_net(global_features) # [Batch, 1]
        
        # 3. Action Logits (Scores)
        # Expand global features to each parcel: [Batch, N, Kg]
        global_expanded = global_features.unsqueeze(1).expand(batch_size, n_swappable, self.k_global)
        
        # Concat: [Batch, N, Kp + Kg]
        inputs = torch.cat([parcel_features, global_expanded], dim=2)
        
        # Score: [Batch, N, 1] -> [Batch, N]
        scores = self.scorer_net(inputs).squeeze(2)
        
        # 4. Masking & Distribution
        dist = self._get_action_dist_from_logits(scores, action_masks)
        
        if deterministic:
            actions = dist.mode()
        else:
            actions = dist.sample()
            
        log_prob = dist.log_prob(actions)
        
        return actions, values, log_prob

    def _get_action_dist_from_logits(self, logits, action_masks):
        """
        Apply masking and return distribution.
        """
        if action_masks is not None:
            # Ensure action_masks is a tensor on the correct device
            if not isinstance(action_masks, torch.Tensor):
                action_masks = torch.as_tensor(action_masks, device=logits.device, dtype=torch.bool)
            
            # Handle shape mismatch: logits [B, N], masks [N]
            if action_masks.ndim == 1 and logits.ndim == 2:
                action_masks = action_masks.unsqueeze(0) # [1, N]
                # If logits has batch > 1, expand mask?
                # Usually predict() with single env means B=1.
                if logits.shape[0] > 1:
                    action_masks = action_masks.expand(logits.shape[0], -1)

            # SB3 MaskablePPO logic: set masked logits to huge negative
            logits[~action_masks] = -1e8
            
        return self.action_dist.proba_distribution(action_logits=logits)

    def predict_values(self, obs):
        """Get value estimate."""
        global_features = obs[:, -self.k_global:]
        return self.value_net(global_features)

    def get_distribution(self, obs, action_masks=None):
        """Get action distribution."""
        # Need to re-run the scoring logic
        batch_size = obs.shape[0]
        n_swappable = (obs.shape[1] - self.k_global) // self.k_parcel
        
        global_features = obs[:, -self.k_global:]
        parcel_flat = obs[:, :-self.k_global]
        parcel_features = parcel_flat.view(batch_size, n_swappable, self.k_parcel)
        
        global_expanded = global_features.unsqueeze(1).expand(batch_size, n_swappable, self.k_global)
        inputs = torch.cat([parcel_features, global_expanded], dim=2)
        
        scores = self.scorer_net(inputs).squeeze(2)
        
        return self._get_action_dist_from_logits(scores, action_masks)
