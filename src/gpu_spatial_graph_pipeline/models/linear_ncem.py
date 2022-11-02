"""
LinearNCEM module
"""
import torch
import torch.nn as nn
import pytorch_lightning as pl
import torch.optim as optim
from sklearn.metrics import r2_score
from ..models.modules.linear_model import LinearNonSpatial, LinearSpatial
import numpy as np
from torch_geometric.data import Batch


class LinearNCEM(pl.LightningModule):
    def __init__(self, model_type="spatial", use_node_scale=False, **model_kwargs):
        super().__init__()
        # Saving hyperparameters
        self.save_hyperparameters(model_kwargs)

        self.use_node_scale = use_node_scale
        self.model_type = model_type

        if self.model_type.casefold() == "spatial":

            self.model_sigma = LinearSpatial(
                in_channels=self.hparams.in_channels,
                out_channels=self.hparams.out_channels,
            )
            self.model_mu = LinearSpatial(
                in_channels=self.hparams.in_channels,
                out_channels=self.hparams.out_channels,
            )

        elif self.model_type.casefold() == "nonspatial":

            self.model_sigma = LinearNonSpatial(
                in_channels=self.hparams.in_channels,
                out_channels=self.hparams.out_channels,
            )
            self.model_mu = LinearNonSpatial(
                in_channels=self.hparams.in_channels,
                out_channels=self.hparams.out_channels,
            )
        else:
            raise ValueError(
                "An invalid model type has been used as input. Valid types: 'spatial' or 'nonspatial'"
            )

        self.loss_module = nn.GaussianNLLLoss(eps=1e-5)

    @staticmethod
    def add_model_specific_args(parent_parser):
        parser = parent_parser.add_argument_group("LinearNCEM")
        parser.add_argument(
            "--lr", type=float, default=0.1, help="the initial learning rate"
        )
        parser.add_argument(
            "--type",
            type=str,
            default="spatial",
            help="type of linear model to use (spatial or nonspatial)",
        )
        parser.add_argument(
            "--use_node_scale",
            type=bool,
            default=True,
            help="whether to use scale factor to scale nodes",
        )
        parser.add_argument(
            "--weight_decay", type=float, default=2e-3, help="the weight decay"
        )
        return parent_parser

    def forward(self, data):
        x = data.x
        mu = self.model_mu(x)
        sigma = torch.exp(self.model_sigma(x))

        # scale by sf
        if self.use_node_scale:
            sf = torch.unsqueeze(data.sf, 1)  # Nx1
            mu = sf * mu
            sigma = sf * sigma

        # clip output
        bound = 60.0
        mu = torch.clamp(mu, min=-np.exp(bound), max=np.exp(bound))
        sigma = torch.clamp(sigma, min=-bound, max=bound)
        return mu, sigma

    def configure_optimizers(self):
        optimizer = optim.Adam(
            self.parameters(),
            lr=self.hparams["lr"],
            weight_decay=self.hparams["weight_decay"],
        )
        return optimizer

    def training_step(self, batch, _):
        if type(batch) == list or type(batch) == tuple:
            self.batch_size = len(batch)
            batch = Batch.from_data_list(batch)
        mu, sigma = self.forward(batch)
        loss = self.loss_module(
            mu[: self.batch_size], batch.y[: self.batch_size], sigma[: self.batch_size]
        )
        self.log("train_loss", loss, batch_size=self.batch_size)
        return loss

    def validation_step(self, batch, _):
        if type(batch) == list or type(batch) == tuple:
            self.batch_size = len(batch)
            batch = Batch.from_data_list(batch)
        mu, sigma = self.forward(batch)
        val_loss = self.loss_module(
            mu[: self.batch_size], batch.y[: self.batch_size], sigma[: self.batch_size]
        )
        val_r2_score = r2_score(
            batch.y.cpu()[: self.batch_size], mu.cpu()[: self.batch_size]
        )
        self.log(
            "val_r2_score", val_r2_score, prog_bar=True, batch_size=self.batch_size
        )
        self.log("val_loss", val_loss, prog_bar=True, batch_size=self.batch_size)

    def test_step(self, batch, _):
        if type(batch) == list:
            self.batch_size = len(batch)
            batch = Batch.from_data_list(batch)
        mu, sigma = self.forward(batch)
        test_loss = self.loss_module(
            mu[: self.batch_size], batch.y[: self.batch_size], sigma[: self.batch_size]
        )
        test_r2_score = r2_score(
            batch.y.cpu()[: self.batch_size], mu.cpu()[: self.batch_size]
        )
        self.log(
            "test_r2_score", test_r2_score, prog_bar=True, batch_size=self.batch_size
        )
        self.log("test_loss", test_loss, prog_bar=True, batch_size=self.batch_size)