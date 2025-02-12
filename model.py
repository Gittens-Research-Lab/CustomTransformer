import torch.nn as nn
import torch, copy
from math import sqrt
import torch.nn.functional as F
from custom_transformer import Encoder
class EBModel(nn.Module):
    def __init__(self, args, device, num_e, num_r):
        super().__init__()
        
        self.device = device
        self.d = args.d
        self.m = args.m
        
        self.num_r = num_r
        self.type_encoding = nn.Parameter(torch.randn(3, self.d))
        if args.agg == 'mean':
            self.effective_d = self.d
            self.target_agg = self.target_mean
            self.neighbor_agg = self.neighbor_mean
        elif args.agg == 'concat':
            self.effective_d = self.d * 4
            self.target_agg = self.target_concat
            self.neighbor_agg = self.neighbor_concat
            self.linear_0 = nn.Linear(self.d * 3, self.effective_d)

        self.edge_bias_encoding_key = nn.Parameter(torch.randn(14, self.effective_d))
        self.edge_bias_encoding_value = nn.Parameter(torch.randn(14, self.effective_d))
        self.r_features = nn.Parameter(torch.randn(num_r, self.d))
        self.e_features = nn.Parameter(torch.randn(num_e, self.d))
        
        self.dim_feedforward = args.ffn * self.d
        self.transformer_encoder = Encoder(self.effective_d, self.dim_feedforward, args.nlayers, args.nheads)

        self.relu = nn.ReLU()
        self.possible_values = torch.arange(self.m).to(device)
        self.lin_ = nn.Linear(self.effective_d, num_r)
        
    
    def get_src(self, target_triple, h_neighbors, t_neighbors, h_n, t_n):
        # construct the sequence of tokens
        # construct the mask for when all m neighbors are not available
        b = target_triple.shape[0]
        target_embed = self.target_agg(self.e_features[target_triple[:,0]], self.e_features[target_triple[:,2]])
        h_neighbor_embed = self.neighbor_agg(self.e_features[h_neighbors[:,:,0]], self.r_features[h_neighbors[:,:,1]], self.e_features[h_neighbors[:,:,2]], 1)
        t_neighbor_embed = self.neighbor_agg(self.e_features[t_neighbors[:,:,0]], self.r_features[t_neighbors[:,:,1]], self.e_features[t_neighbors[:,:,2]], 2)
        
        mask = torch.cat((torch.zeros((b, 1), dtype=torch.bool).to(self.device),\
                          h_n.unsqueeze(1)<=self.possible_values, t_n.unsqueeze(1)<=self.possible_values), dim=1)
        src = torch.cat((target_embed.unsqueeze(1), h_neighbor_embed, t_neighbor_embed), dim=1)
        return src, mask
    def forward(self, target_triple, h_neighbors, t_neighbors, n, adj):
        # target_triple:    Tensor, shape [b, 3]
        # h_neighbors:      Tensor, shape [b, m, 3]
        # t_neighbors:      Tensor, shape [b, m, 3]

        
        # n:                Tensor, shape [b, 2]
        # n (<=m) is the number of neighbor triples we could find

        
        # adj:              Tensor, shape [2m+1, 2m+1]
        # adj is an adjacency matrix which has values 0, 1, 2 etc 
        # depending on the type of connection the tokens share among themselves
        # 2m+1: 1 target entity pair, m neighbors of head entity and m neighbors of tail entity

        edge_bias_key_embed = self.edge_bias_encoding_key[adj]
        edge_bias_value_embed = self.edge_bias_encoding_value[adj]
        src, padding_mask = self.get_src(target_triple, h_neighbors, t_neighbors, n[:,0], n[:,1])
        output = self.transformer_encoder(src, edge_bias_key_embed, edge_bias_value_embed, padding_mask) # output, tensor [b, 2m+1, effective_d]

        # output = output.mean(dim=1) # or use output[:, 0, :]
        output = output[:, 0, :] # [b, 2d]
        return self.lin_(output)
    

    def target_mean(self, a, b):
        return (a+b)/2 + self.type_encoding[0]

    def target_concat(self, a, b):
        batch_size=a.shape[0]
        return self.linear_0(torch.cat((a,b, self.type_encoding[0].repeat(batch_size, 1)),dim=1))
    
    def neighbor_concat(self,a,b,c, idx):
        x, y, z = a.shape
        return torch.cat((a,b,c, self.type_encoding[idx].repeat(x, y, 1)),dim=2)

    def neighbor_mean(self, a,b,c, idx):
        return (a+b+c)/3 + self.type_encoding[idx]

